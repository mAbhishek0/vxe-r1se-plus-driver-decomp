"""Portable VXE R1 SE+ settings tool (tkinter). Talks to the mouse over HID. The only network access is the manual,
opt-in firmware version check (Other tab). Files written: r1se_config.json (theme choice) and r1se_errors.log (errors and
crashes only) next to the exe, plus a config export at a path the user picks. Items marked (unverified) are not
auto-written / were not confirmed on hardware."""
import ctypes
import json
import os
import queue
import sys
import threading
import time
import traceback
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import r1se_tool as t

RATES = t.RATES_1K

PALETTES = {
    'Light': dict(bg='#f3f3f3', fg='#1a1a1a', field='#ffffff', btn='#e1e1e1', btn_act='#d0d0d0', sel='#cce4f7',
                  border='#b5b5b5', muted='#555555', accent='#003366', warn='#aa0000', tip='#ffffe0'),
    'Dark': dict(bg='#202020', fg='#e8e8e8', field='#2b2b2b', btn='#3a3a3a', btn_act='#4a4a4a', sel='#264f78',
                 border='#555555', muted='#a0a0a0', accent='#6cb6ff', warn='#ff6b6b', tip='#3a3a3a'),
}
PAL = PALETTES['Light']


def config_path():
    base = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'r1se_config.json')


def log_error(msg):
    """Appends to r1se_errors.log next to the exe. Called only on errors/crashes, never during normal operation."""
    try:
        p = os.path.join(os.path.dirname(config_path()), 'r1se_errors.log')
        if os.path.exists(p) and os.path.getsize(p) > 1_000_000:
            os.replace(p, p + '.old')
        with open(p, 'a', encoding='utf8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + msg.rstrip() + chr(10))
    except OSError:
        pass


def load_config():
    try:
        with open(config_path(), encoding='utf8') as f:
            c = json.load(f)
        return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    try:
        with open(config_path(), 'w', encoding='utf8') as f:
            json.dump(cfg, f, indent=1)
    except OSError:
        pass                    # read-only location: the setting just isn't remembered


def watch_system_theme(callback):
    """Calls callback() from a daemon thread whenever Windows changes the personalization registry key
    (dark/light switch). Event-driven (RegNotifyChangeKeyValue), no polling. Returns stop(), which closes the key."""
    keys = []

    def stop():
        for k in keys:
            k.Close()

    def run():
        try:
            import winreg
            from ctypes import wintypes
            notify = ctypes.windll.advapi32.RegNotifyChangeKeyValue
            notify.argtypes = (wintypes.HKEY, wintypes.BOOL, wintypes.DWORD, wintypes.HANDLE, wintypes.BOOL)
            notify.restype = wintypes.LONG
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize',
                                0, winreg.KEY_NOTIFY) as key:
                keys.append(key)
                while notify(key.handle, False, 4, None, False) == 0:      # 4 = REG_NOTIFY_CHANGE_LAST_SET
                    callback()
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()
    return stop


def system_theme():
    """'Dark' or 'Light' following the Windows app-mode setting (Light if undetectable)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as k:
            return 'Light' if winreg.QueryValueEx(k, 'AppsUseLightTheme')[0] else 'Dark'
    except Exception:
        return 'Light'


class Tip:
    """Hover tooltip: appears after a short delay, hides on leave/click."""
    def __init__(self, w, text):
        self.w, self.text, self.tw, self.job = w, text, None, None
        w.bind('<Enter>', self.schedule, add='+')
        w.bind('<Leave>', self.hide, add='+')
        w.bind('<ButtonPress>', self.hide, add='+')

    def schedule(self, _):
        self.hide(None)
        self.job = self.w.after(450, self.show)

    def show(self):
        self.job = None
        if self.tw:
            return
        self.tw = tk.Toplevel(self.w)
        self.tw.wm_overrideredirect(True)
        self.tw.wm_geometry('+%d+%d' % (self.w.winfo_rootx() + 12, self.w.winfo_rooty() + self.w.winfo_height() + 4))
        tk.Label(self.tw, text=self.text, background=PAL['tip'], foreground=PAL['fg'], relief='solid', borderwidth=1,
                 wraplength=340, justify='left', padx=6, pady=4).pack()

    def hide(self, _):
        if self.job:
            self.w.after_cancel(self.job)
            self.job = None
        if self.tw:
            self.tw.destroy()
            self.tw = None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('R1 SE+ Portable')
        self.resizable(False, False)
        self.dev = None
        self.r = None
        self.q = queue.Queue()          # callables for the UI thread
        self.jobs = queue.Queue()       # device jobs, run in FIFO order by one worker thread
        self.pending = 0                # queued + running device jobs (UI thread only)
        self.closing = self.closed = False
        threading.Thread(target=self.worker, daemon=True).start()
        self.after(100, self.poll)
        self.status = tk.StringVar(value='Not connected')
        self.style = ttk.Style(self)
        self.cfg = load_config()
        self.theme_mode = tk.StringVar(value=self.cfg.get('theme') if self.cfg.get('theme') in ('System', 'Light', 'Dark') else 'System')
        self.applied = None
        self.info = tk.StringVar(value='Not connected')
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill='x')
        ttk.Label(top, textvariable=self.info).pack(side='left')
        ttk.Button(top, text='Refresh all', command=self.refresh).pack(side='right')
        tc = ttk.Combobox(top, textvariable=self.theme_mode, values=('System', 'Light', 'Dark'), state='readonly', width=8)
        tc.pack(side='right', padx=(0, 8))
        tc.bind('<<ComboboxSelected>>', lambda e: (self.apply_theme(), self.cfg.update(theme=self.theme_mode.get()),
                                                   save_config(self.cfg)))
        ttk.Label(top, text='Theme').pack(side='right', padx=(0, 4))
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill='both', padx=8)
        ttk.Label(self, textvariable=self.status, style='Muted.TLabel', padding=(10, 6)).pack(fill='x')
        self.build_keys()
        self.build_macros()
        self.build_dpi()
        self.build_perf()
        self.build_param()
        self.build_config()
        self.build_other()
        self.add_tips()
        self.apply_theme()
        self.stop_theme_watch = watch_system_theme(lambda: self.q.put(self.on_system_theme))
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        self.refresh()

    def on_close(self):
        """Never destroys the window under a running write: pending device jobs finish first, then the worker closes
        the device and the window is destroyed."""
        if self.closing:
            return
        if self.pending and not messagebox.askyesno(
                'Close', 'A device operation is still running (%d pending). Close the window when it has finished?\n'
                         '(No keeps the window open.)' % self.pending):
            return
        self.closing = True
        self.status.set('Closing: waiting for pending device operations...')
        self.jobs.put(None)             # sentinel, handled by the worker after all queued jobs

    def _destroy(self):
        self.closed = True
        self.stop_theme_watch()
        self.destroy()

    # ------------------------------------------------------------ tooltips
    def add_tips(self):
        def walk(w):
            yield w
            for c in w.winfo_children():
                yield from walk(c)

        def attach(root, by_text, by_var):
            for w in walk(root):
                keys = w.keys()
                txt = str(w.cget('text')) if 'text' in keys else ''
                tv = str(w.cget('textvariable')) if 'textvariable' in keys else ''
                tip = by_var.get(tv) if tv else None
                tip = tip or (by_text.get(txt) if txt else None)
                if tip:
                    Tip(w, tip)

        theme_tip = 'Window colors. System follows the Windows light/dark setting; the choice is remembered.'
        attach(self, {'Refresh all': 'Re-read every setting from the mouse and update this window.', 'Theme': theme_tip},
               {str(self.theme_mode): theme_tip,
                str(self.info): 'Mouse model id (cid,mid), mouse firmware, dongle firmware and battery level.',
                str(self.status): 'Result of the last action. Errors are also written to r1se_errors.log.'})

        names = {
            0: 'Left mouse button (primary click). It cannot be disabled, and at least one of Left/Right always stays a '
               'mouse click, so you cannot lock yourself out.',
            1: 'Right mouse button. It cannot be disabled, and at least one of Left/Right always stays a mouse click, '
               'so you cannot lock yourself out.',
            2: 'Click of the scroll wheel.',
            3: 'Back side button (thumb).',
            4: 'Forward side button (thumb).',
            5: 'Button that steps through the DPI stages.',
        }
        kt = {t.BUTTONS[k]: v for k, v in names.items()}
        kt.update({
            'Ctrl': 'Hold Ctrl together with the chosen key. Used only by the Keyboard category.',
            'Shift': 'Hold Shift together with the chosen key. Used only by the Keyboard category.',
            'Alt': 'Hold Alt together with the chosen key. Used only by the Keyboard category.',
            'Win': 'Hold the Windows key together with the chosen key. Used only by the Keyboard category.',
            'Apply': 'Write the chosen action to this button on the mouse now (stored on the mouse).',
            'Restore Default': 'Reset all six buttons to their default actions. DPI and other settings are not changed.',
        })
        kv = {}
        for k in range(len(t.BUTTONS)):
            kv[str(self.key_cur[k])] = 'Action currently stored on the mouse for this button (read from the device).'
            kv[str(self.key_cat[k])] = ('Kind of action: mouse buttons, config switch, DPI, wheel, multimedia, or a keyboard '
                                        'key/shortcut. Nothing is written until you press Apply.')
            kv[str(self.key_act[k])] = 'The action to assign to this button. Nothing is written until you press Apply.'
        mt = {
            'Save to selected slot': 'Write the typed macro into the selected slot on the mouse (read back and verified after writing).',
            'Delete selected': 'Erase the selected macro slot on the mouse.',
            'Assign': 'Bind the selected macro to the chosen button, using the chosen repeat mode.',
            'Assign to button:': 'Button that will trigger the selected macro.',
            'Steps (KEY+ down / KEY- up / @ms delay), e.g.  A+ A- @50 B+ B-':
                'Macro steps separated by spaces: KEY+ presses a key, KEY- releases it, @50 waits 50 ms.',
        }
        mv = {str(self.macro_txt): 'Type the macro steps here, e.g. A+ A- @50 B+ B-  (press A, release A, wait 50 ms, press B, release B).',
              str(self.m_btn): 'Button that will trigger the selected macro.',
              str(self.m_mode): 'How the macro runs: once, repeating until the next press, repeating until any mouse button, or stop immediately.'}
        dt = {'Active': 'The radio buttons choose which DPI stage the mouse uses now (applied with Apply).',
              'X DPI': 'Horizontal sensitivity per stage.', 'Y DPI': 'Vertical sensitivity per stage.',
              'Apply': 'Write all four stages and the active stage to the mouse.'}
        dv = {}
        for i in range(4):
            dt['Stage %d' % (i + 1)] = 'Make stage %d the active DPI stage (applied with Apply).' % (i + 1)
            dv[str(self.dx[i])] = ('Horizontal DPI for stage %d. Rounded to 50 DPI steps up to 10000 and 100 DPI steps above, '
                                   'max 18000. Applied with Apply.' % (i + 1))
            dv[str(self.dy[i])] = ('Vertical DPI for stage %d. Rounded to 50 DPI steps up to 10000 and 100 DPI steps above, '
                                   'max 18000. Applied with Apply.' % (i + 1))
        poll = 'Polling rate: how often the mouse reports its position. Higher means lower latency and more power use. Applied immediately.'
        pt = {'Polling rate': poll, 'Hz': poll,
              'Mode': 'Sensor performance profile.',
              'Daily Work (Basic Mode)': 'Sensor in a lower-performance state: longer battery life, suited to office use. Applied immediately.',
              'Game Competitive (ATK Shard Competitive Firmware)': 'Higher sensor performance for gaming; uses more power. Applied immediately.'}
        pv = {str(self.rate): poll}
        rt = {'Movement Sync': 'Smooths movement with algorithm correction for accurate trajectories; adds minor latency. Applied immediately.',
              'Straight Line Correction': 'Removes jitter when you move in a straight line, useful for drawing and design. Applied immediately.',
              'Ripple Correction': 'Corrects wave-like jitter at high movement speed. Applied immediately.',
              'Ultra Long Range mode': 'Improves wireless performance at long distance but increases power consumption. Applied immediately.',
              'Key debounce (ms)': 'Ignores clicks repeated within this time, preventing double-clicks from switch bounce. Lower is faster, higher filters more. Applied immediately.',
              'Sleep time': 'Idle time before the mouse enters sleep to save battery; move it to wake it. Applied immediately.',
              'Lift-off distance (mm)': 'Height above the surface at which the sensor stops tracking (1 or 2 mm). Applied immediately.',
              'DPI light': 'Effect of the LED that shows the current DPI stage: Close (off), Always On or Breathing. Applied with Apply light.',
              'Brightness': 'Brightness of the DPI light. Applied with Apply light.',
              'Speed': 'Breathing speed of the DPI light (Slow, Medium, Fast). Applied with Apply light.',
              'Apply light': 'Write the DPI light effect, brightness and speed to the mouse.'}
        rv = {str(self.debounce): rt['Key debounce (ms)'], str(self.sleep): rt['Sleep time'],
              str(self.lod): rt['Lift-off distance (mm)'], str(self.leffect): rt['DPI light'],
              str(self.lbright): rt['Brightness'], str(self.lspeed): rt['Speed']}
        ct = {'Onboard config file': 'The mouse stores four profiles; this selects the one in use. Applied immediately.',
              'Export to file...': 'Save the mouse settings (rate, DPI, buttons, parameters, macros) to a JSON file you choose.',
              'Import from file...': 'Load a saved file. Checksums are validated and only known settings are written.'}
        for i in range(4):
            ct[str(i + 1)] = 'Switch to onboard config file %d. Applied immediately.' % (i + 1)
        ot = {'Check for firmware update': 'Manual check only: up to two requests to the vendor server (api-hub-cloud.atk.pro) with the USB IDs and model in the URL '
                                           '(R1 SE+ mouse IDs first; the connected dongle IDs only as a fallback, which may return the dongle firmware instead). It never installs firmware.',
              'Pair receiver...': 'Starts wireless pairing between the mouse and the dongle. The mouse may disconnect until paired. Not tested on hardware.',
              'Factory reset...': 'Erases ALL settings and macros on the mouse after two confirmations. Not tested on hardware.'}
        ov = {str(self.other_txt): 'Read-only device information from the mouse and dongle.',
              str(self.fw_txt): 'Result of the firmware check.'}
        tabs = {self.nb.tab(i, 'text'): self.nb.nametowidget(i) for i in self.nb.tabs()}
        for name, (bt, bv) in {'Key Change Settings': (kt, kv), 'Macro Settings': (mt, mv), 'DPI Settings': (dt, dv),
                               'Performance': (pt, pv), 'Parameter': ({**pt, **rt}, {**pv, **rv}), 'Config': (ct, {}),
                               'Other': (ot, ov)}.items():
            attach(tabs[name], bt, bv)
        Tip(self.macro_list, 'Macro slots stored on the mouse. Select one to edit it.')

    # ------------------------------------------------------------ theme
    def on_system_theme(self):
        if self.theme_mode.get() == 'System' and system_theme() != self.applied:
            self.apply_theme()

    def apply_theme(self):
        global PAL
        name = system_theme() if self.theme_mode.get() == 'System' else self.theme_mode.get()
        self.applied = name
        PAL = c = PALETTES[name]
        st = self.style
        st.theme_use('clam')
        self.configure(background=c['bg'])
        st.configure('.', background=c['bg'], foreground=c['fg'], fieldbackground=c['field'], bordercolor=c['border'],
                     lightcolor=c['bg'], darkcolor=c['bg'], troughcolor=c['field'], selectbackground=c['sel'],
                     selectforeground=c['fg'], insertcolor=c['fg'])
        st.configure('TButton', background=c['btn'], foreground=c['fg'], bordercolor=c['border'], padding=(8, 3))
        st.map('TButton', background=[('active', c['btn_act']), ('disabled', c['bg'])],
               foreground=[('disabled', c['muted'])])
        st.configure('TNotebook', background=c['bg'], bordercolor=c['border'])
        st.configure('TNotebook.Tab', background=c['btn'], foreground=c['fg'], padding=(10, 4), bordercolor=c['border'])
        st.map('TNotebook.Tab', background=[('selected', c['bg']), ('active', c['btn_act'])])
        st.configure('TCombobox', fieldbackground=c['field'], background=c['btn'], foreground=c['fg'],
                     arrowcolor=c['fg'], bordercolor=c['border'])
        st.map('TCombobox', fieldbackground=[('readonly', c['field'])], foreground=[('readonly', c['fg'])],
               selectbackground=[('readonly', c['field'])], selectforeground=[('readonly', c['fg'])])
        st.configure('TEntry', fieldbackground=c['field'], foreground=c['fg'], bordercolor=c['border'])
        for w in ('TRadiobutton', 'TCheckbutton'):
            st.configure(w, background=c['bg'], foreground=c['fg'], indicatorbackground=c['field'],
                         indicatorforeground=c['fg'])
            st.map(w, background=[('active', c['bg'])], indicatorbackground=[('selected', c['sel'])])
        st.configure('Muted.TLabel', foreground=c['muted'])
        st.configure('Accent.TLabel', foreground=c['accent'])
        st.configure('Warn.TLabel', foreground=c['warn'])
        self.option_add('*TCombobox*Listbox.background', c['field'])
        self.option_add('*TCombobox*Listbox.foreground', c['fg'])
        self.option_add('*TCombobox*Listbox.selectBackground', c['sel'])
        self.option_add('*TCombobox*Listbox.selectForeground', c['fg'])
        if hasattr(self, 'macro_list'):
            self.macro_list.configure(background=c['field'], foreground=c['fg'], selectbackground=c['sel'],
                                      selectforeground=c['fg'], highlightbackground=c['border'], relief='flat')
        try:    # dark title bar on Windows 10/11
            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            v = ctypes.c_int(1 if name == 'Dark' else 0)
            for attr in (20, 19):
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
        except Exception:
            pass

    # ------------------------------------------------------------ infra
    def tab(self, name):
        f = ttk.Frame(self.nb, padding=12)
        self.nb.add(f, text=name)
        return f

    def bg(self, fn, done=None, msg='Working... (move the mouse if it is asleep)', need_dev=True):
        """Queue fn(dev) for the worker thread (FIFO, device access serialised); done(result) runs on the UI thread.
        fn must not touch Tk variables: read them on the UI thread and pass plain values in."""
        if self.closing:
            return
        self.pending += 1
        self.status.set(msg)
        self.jobs.put((fn, done, need_dev))

    def worker(self):
        while True:
            job = self.jobs.get()
            if job is None:                 # window closing: every earlier job has finished
                if self.dev is not None:
                    self.dev.close()
                    self.dev = None
                self.q.put(self._destroy)
                return
            fn, done, need_dev = job
            try:
                if need_dev and self.dev is None:
                    self.dev = t.Dev(timeout=2.5, retries=3)
                res, err, reset = fn(self.dev), None, False
            except SystemExit as e:
                res, err, reset = None, str(e), True
                log_error('ERROR ' + err)
            except Exception as e:
                res, err, reset = None, '%s: %s' % (type(e).__name__, e), not isinstance(e, ValueError)
                log_error('ERROR ' + (err if isinstance(e, TimeoutError) else traceback.format_exc()))
            if reset and self.dev is not None:   # unplug / replug / cable <-> dongle: reopen on the next job
                self.dev.close()
                self.dev = None
            self.q.put(lambda done=done, res=res, err=err: self.finish(done, res, err))

    def finish(self, done, res, err):
        self.pending -= 1
        if self.closing:
            self.status.set('Closing: waiting for pending device operations...')
            return
        if err:
            self.status.set('Error: %s' % err)
        else:
            self.status.set('OK')
            if done:
                done(res)

    def poll(self):
        """Runs queued UI callbacks; one failing callback is logged and shown, and polling always continues."""
        try:
            while not self.closed:
                try:
                    cb = self.q.get_nowait()
                except queue.Empty:
                    break
                try:
                    cb()
                except Exception as e:
                    log_error('ERROR (ui queue) ' + traceback.format_exc())
                    if not self.closed:
                        self.status.set('Error: %s: %s' % (type(e).__name__, e))
        finally:
            if not self.closed:
                self.after(100, self.poll)

    def write_then_refresh(self, fn, what='Applied'):
        self.bg(fn, lambda _: (self.status.set(what + ' - verifying'), self.refresh()))

    def setv(self, fn, *args, what='Set', **kw):
        """write_then_refresh(fn(dev, *args, **kw)); call it on the UI thread so Tk values are read here, not in the worker."""
        self.write_then_refresh(lambda d: fn(d, *args, **kw), what)

    def refresh(self):
        def rd(d):
            r = {}
            r['info'] = t.get_info(d)
            r['rate'] = t.get_rate(d)[0]
            r['dpi'] = t.get_dpi(d)
            r['func'] = t.get_func(d)
            r['lod'] = t.get_lod(d)[0]
            r['sensor'] = t.get_sensor_mode(d)
            r['far'] = t.get_far(d)
            r['light'] = t.get_light(d)
            r['profile'] = t.get_profile(d)
            r['buttons'] = t.get_buttons(d)
            r['short'] = {i: t.get_shortcut(d, i) for i, b in enumerate(r['buttons']) if b[0] == 5}
            r['macros'] = [t.macro_get(d, k) for k in range(t.MACRO_SLOTS)]
            try:
                r['dlight'] = t.get_dongle_light(d)
                r['rgb4k'] = t.get_4k_rgb(d)
            except TimeoutError:
                r['dlight'] = r['rgb4k'] = None
            return r
        self.bg(rd, self.fill)

    def fill(self, r):
        i = r['info']
        self.info.set('cid,mid %d,%d   fw %s   dongle fw %s   battery %d%%%s' % (
            i['cid'], i['mid'], i['fw'], i['dongle_fw'], i['battery']['percent'],
            ' (charging)' if i['battery']['charging'] else ''))
        self.r = r
        for k, (c, b) in enumerate(zip(self.key_cur, r['buttons'])):
            c.set(t.describe_button(b, r['short'].get(k)))
        self.macro_list.delete(0, 'end')
        for k, m in enumerate(r['macros']):
            self.macro_list.insert('end', 'M%d: %s' % (k + 1, '(empty)' if m is None else t.macro_to_text(m['actions'])))
        dp = r['dpi']
        for n in range(4):
            x, y = dp['stages'][n]
            self.dx[n].set('?' if x is None else str(x))
            self.dy[n].set('?' if y is None else str(y))
        self.cur.set(dp['current'] if dp['current'] < 4 else 0)
        self.dpi_count.set('Stages enabled on the mouse: %d (the active stage must be one of them).' % dp['count'])
        if r['rate'] in RATES:
            self.rate.set(str(r['rate']))
        self.sensor.set(r['sensor']['mode'] if r['sensor']['mode'] in (0, 1) else 0)
        f = r['func']
        self.debounce.set(str(f['debounce']))
        self.sleep.set(self.sleep_label(f['sleep_s']))
        self.msync.set(f['motion_sync'])
        self.line.set(f['line_corr'])
        self.ripple.set(f['ripple'])
        self.far.set(r['far'])
        self.lod.set(str(r['lod']))
        lg = r['light']
        self.leffect.set(lg['effect'] if lg['effect'] in t.LIGHT_MODES else 'Close')
        self.lbright.set(next((k for k, v in t.LIGHT_BRIGHT.items() if v == lg['brightness']), 'Medium'))
        self.lspeed.set(next((k for k, v in t.LIGHT_SPEED.items() if v == lg['speed']), 'Medium'))
        self.profile.set(r['profile'])
        self.other_txt.set('Firmware: %s\nDongle firmware: %s\nBattery: %d%% (%d mV)\nDongle light (read only): %s\n4K RGB mode (read only): %s' % (
            i['fw'], i['dongle_fw'], i['battery']['percent'], i['battery']['mv'], r['dlight'], r['rgb4k']))

    @staticmethod
    def sleep_label(s):
        return '%ds' % s if s < 60 else '%dmin' % (s // 60)

    # ------------------------------------------------------------ 1 keys
    def build_keys(self):
        f = self.tab('Key Change Settings')
        self.cat = t.action_catalog()
        cats = list(self.cat) + ['Keyboard / Shortcut Command', 'Special (fire key)']
        self.key_cur = [tk.StringVar() for _ in t.BUTTONS]
        self.key_cat = [tk.StringVar() for _ in t.BUTTONS]
        self.key_act = [tk.StringVar() for _ in t.BUTTONS]
        self.key_mod = [{m: tk.IntVar() for m in ('Ctrl', 'Shift', 'Alt', 'Win')} for _ in t.BUTTONS]
        order = [2, 4, 3, 0, 1, 5]      # Middle, Advance, Back, Left, Right, DPI as in the vendor UI
        for row, k in enumerate(order):
            ttk.Label(f, text=t.BUTTONS[k], width=16).grid(row=row, column=0, sticky='w', pady=2)
            ttk.Label(f, textvariable=self.key_cur[k], width=30, style='Accent.TLabel').grid(row=row, column=1, sticky='w')
            cc = ttk.Combobox(f, textvariable=self.key_cat[k], values=cats, state='readonly', width=22)
            cc.grid(row=row, column=2, padx=4)
            ac = ttk.Combobox(f, textvariable=self.key_act[k], state='readonly', width=20)
            ac.grid(row=row, column=3, padx=4)
            mods = ttk.Frame(f)
            mods.grid(row=row, column=4)
            for m, v in self.key_mod[k].items():
                ttk.Checkbutton(mods, text=m, variable=v).pack(side='left')
            ttk.Button(f, text='Apply', command=lambda k=k: self.apply_key(k)).grid(row=row, column=5, padx=4)
            cc.bind('<<ComboboxSelected>>', lambda e, k=k, ac=ac: self.cat_changed(k, ac))
            self.key_cat[k].set(cats[0])
            self.cat_changed(k, ac)
        ttk.Button(f, text='Restore Default', command=self.restore_keys).grid(row=7, column=0, pady=(10, 0), sticky='w')
        ttk.Label(f, style='Muted.TLabel', wraplength=720, justify='left',
                  text='Disabling Left/Right is blocked and at least one of Left/Right always stays a mouse click. Keyboard shortcuts with Ctrl/Shift/Alt/Win are verified on hardware; '
                       'the fire key (Special) is unverified and not written. Modifier boxes apply to the Keyboard category only.'
                  ).grid(row=8, columnspan=6, sticky='w', pady=(8, 0))

    def cat_changed(self, k, ac):
        c = self.key_cat[k].get()
        if c in self.cat:
            ac['values'] = list(self.cat[c])
        elif c.startswith('Keyboard'):
            ac['values'] = list(t.KEYS)
        else:
            ac['values'] = ['(unverified - disabled)']
        ac.set(ac['values'][0])

    def apply_key(self, k):
        c, a = self.key_cat[k].get(), self.key_act[k].get()
        if c.startswith('Special'):
            messagebox.showinfo('Unverified', 'Fire key semantics (interval/count units) are unverified; not written.')
            return
        if c in self.cat:
            spec = self.cat[c][a]
        else:
            mods = [m for m, v in self.key_mod[k].items() if v.get()]
            spec = ('short', t.key_actions(a, mods))
        if k in (0, 1):                 # same rule as t.check_button (which re-checks against the device)
            cls, v1 = (spec[1], spec[2]) if spec[0] == 'key' else (5, 0)
            other = self.r['buttons'][1 - k] if self.r else None
            if t.button_lockout(k, cls, v1) or not (t.is_click(cls, v1) or (other and other[3] and t.is_click(*other[:2]))):
                messagebox.showwarning('Refused', 'Left/Right cannot be disabled, and at least one of Left/Right always '
                                                  'stays a mouse click, so you cannot lock yourself out.')
                return
        if k in (0, 1) and not messagebox.askyesno('Confirm', 'Remap %s? Make sure you can still click.' % t.BUTTONS[k]):
            return
        self.write_then_refresh(lambda d: t.apply_action(d, k, spec), 'Button remapped')

    def restore_keys(self):
        if messagebox.askyesno('Restore Default', 'Reset all 6 buttons to defaults?'):
            self.write_then_refresh(lambda d: t.restore_default_buttons(d), 'Buttons restored')

    # ------------------------------------------------------------ 2 macros
    def build_macros(self):
        f = self.tab('Macro Settings')
        self.macro_list = tk.Listbox(f, width=60, height=12, exportselection=False)
        self.macro_list.grid(row=0, column=0, columnspan=4, sticky='w')
        ttk.Label(f, text='Steps (KEY+ down / KEY- up / @ms delay), e.g.  A+ A- @50 B+ B-').grid(row=1, column=0, columnspan=4, sticky='w', pady=(8, 0))
        self.macro_txt = tk.StringVar()
        ttk.Entry(f, textvariable=self.macro_txt, width=62).grid(row=2, column=0, columnspan=4, sticky='w')
        ttk.Button(f, text='Save to selected slot', command=self.macro_save).grid(row=3, column=0, pady=6, sticky='w')
        ttk.Button(f, text='Delete selected', command=self.macro_del).grid(row=3, column=1, sticky='w')
        ttk.Label(f, text='Assign to button:').grid(row=4, column=0, sticky='w')
        self.m_btn = tk.StringVar(value=t.BUTTONS[4])
        ttk.Combobox(f, textvariable=self.m_btn, values=t.BUTTONS[2:5], state='readonly', width=18).grid(row=4, column=1)
        self.m_mode = tk.StringVar(value='Run once')
        ttk.Combobox(f, textvariable=self.m_mode, values=('Run once', 'Repeat until next press', 'Repeat until any mouse button',
                                                          'Stop immediately'), state='readonly', width=22).grid(row=4, column=2)
        ttk.Button(f, text='Assign', command=self.macro_assign).grid(row=4, column=3)
        ttk.Label(f, style='Warn.TLabel', wraplength=620, justify='left',
                  text='Macros are stored on the mouse and written as one uninterrupted stream (verified on hardware: save, rewrite, delete on several slots). '
                       'All three run modes and the millisecond delay unit are verified on hardware.').grid(row=5, columnspan=4, sticky='w', pady=(8, 0))
        self.macro_list.bind('<<ListboxSelect>>', self.macro_sel)

    def macro_sel(self, _):
        s = self.macro_list.curselection()
        if s and self.r and self.r['macros'][s[0]]:
            self.macro_txt.set(t.macro_to_text(self.r['macros'][s[0]]['actions']))

    def _slot(self):
        s = self.macro_list.curselection()
        if not s:
            messagebox.showinfo('Macro', 'Select a slot first')
        return s[0] if s else None

    def macro_save(self):
        k = self._slot()
        if k is None:
            return
        try:
            acts = t.macro_from_text(self.macro_txt.get())
            t.macro_encode(acts)
        except ValueError as e:
            return messagebox.showerror('Macro', str(e))
        self.write_then_refresh(lambda d: t.macro_set(d, k, acts), 'Macro saved')

    def macro_del(self):
        k = self._slot()
        if k is not None:
            self.write_then_refresh(lambda d: t.macro_delete(d, k), 'Macro deleted')

    def macro_assign(self):
        k = self._slot()
        if k is None:
            return
        idx = t.BUTTONS.index(self.m_btn.get())
        mode = {'Run once': 1, 'Repeat until next press': 253, 'Repeat until any mouse button': 255, 'Stop immediately': 254}[self.m_mode.get()]
        self.write_then_refresh(lambda d: t.assign_macro(d, idx, k, mode), 'Macro assigned')

    # ------------------------------------------------------------ 3 dpi
    def build_dpi(self):
        f = self.tab('DPI Settings')
        self.dx = [tk.StringVar() for _ in range(4)]
        self.dy = [tk.StringVar() for _ in range(4)]
        self.cur = tk.IntVar(value=0)
        ttk.Label(f, text='Active').grid(row=0, column=0)
        ttk.Label(f, text='X DPI').grid(row=0, column=2)
        ttk.Label(f, text='Y DPI').grid(row=0, column=3)
        for i in range(4):
            ttk.Radiobutton(f, text='Stage %d' % (i + 1), variable=self.cur, value=i).grid(row=i + 1, column=0, sticky='w')
            ttk.Entry(f, textvariable=self.dx[i], width=8).grid(row=i + 1, column=2, padx=4, pady=2)
            ttk.Entry(f, textvariable=self.dy[i], width=8).grid(row=i + 1, column=3, padx=4)
        ttk.Button(f, text='Apply', command=self.apply_dpi).grid(row=6, column=0, pady=(10, 0), sticky='w')
        ttk.Label(f, style='Muted.TLabel', text='Values are rounded to the sensor table (50 DPI steps up to 10000, 100 DPI '
                                                'steps above, max 18000). A stage showing ? has an unknown code and is not written.'
                  ).grid(row=7, columnspan=4, sticky='w', pady=6)
        self.dpi_count = tk.StringVar()
        ttk.Label(f, textvariable=self.dpi_count, style='Muted.TLabel').grid(row=8, columnspan=4, sticky='w')

    def apply_dpi(self):
        try:
            vals = {}
            for i in range(4):
                sx, sy = self.dx[i].get().strip(), self.dy[i].get().strip()
                if '?' in (sx, sy):
                    continue                # unknown code read from the mouse: leave that stage untouched
                vals[i] = (int(sx), int(sy))
                t.dpi_encode(*vals[i])
        except ValueError as e:
            return messagebox.showerror('DPI', 'Invalid DPI: %s' % e)
        c = self.cur.get()
        count = self.r['dpi']['count'] if self.r else None
        if count is not None and c >= count:
            return messagebox.showerror('DPI', 'Stage %d is not enabled on the mouse (it has %d stages).' % (c + 1, count))

        def w(d):
            for n, (x, y) in vals.items():
                t.set_dpi_stage(d, n, x, y)
            t.set_dpi_current(d, c)
        self.write_then_refresh(w, 'DPI applied')

    # ------------------------------------------------------------ 4 performance
    def build_perf(self):
        f = self.tab('Performance')
        self.rate = tk.StringVar(value='1000')
        self.sensor = tk.IntVar(value=0)
        ttk.Label(f, text='Polling rate').grid(row=0, column=0, sticky='w')
        c = ttk.Combobox(f, textvariable=self.rate, values=RATES, width=6, state='readonly')
        c.grid(row=0, column=1, padx=6)
        ttk.Label(f, text='Hz').grid(row=0, column=2, sticky='w')
        c.bind('<<ComboboxSelected>>', lambda e: self.setv(t.set_rate, int(self.rate.get()), what='Rate set'))
        ttk.Label(f, text='Mode').grid(row=1, column=0, sticky='nw', pady=(14, 0))
        r1 = ttk.Radiobutton(f, text='Daily Work (Basic Mode)', variable=self.sensor, value=0, command=self.apply_sensor)
        r1.grid(row=1, column=1, columnspan=3, sticky='w', pady=(14, 0))
        r2 = ttk.Radiobutton(f, text='Game Competitive (ATK Shard Competitive Firmware)', variable=self.sensor, value=1, command=self.apply_sensor)
        r2.grid(row=2, column=1, columnspan=3, sticky='w')

    def apply_sensor(self):
        v = self.sensor.get()
        self.write_then_refresh(lambda d: t.set_sensor_mode(d, v), 'Mode set')

    # ------------------------------------------------------------ 5 parameter
    def build_param(self):
        f = self.tab('Parameter')
        self.msync, self.line, self.ripple, self.far = (tk.IntVar() for _ in range(4))
        self.debounce, self.sleep, self.lod = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.leffect, self.lbright, self.lspeed = tk.StringVar(), tk.StringVar(), tk.StringVar()
        rows = [('Movement Sync', self.msync, 'motion_sync'), ('Straight Line Correction', self.line, 'line_corr'),
                ('Ripple Correction', self.ripple, 'ripple')]
        for r, (lab, var, key) in enumerate(rows):
            ttk.Checkbutton(f, text=lab, variable=var, command=lambda key=key, var=var: self.setv(
                t.set_func, **{key: var.get()})).grid(row=r, column=0, sticky='w')
        ttk.Checkbutton(f, text='Ultra Long Range mode', variable=self.far,
                        command=lambda: self.setv(t.set_far, self.far.get())).grid(row=3, column=0, sticky='w')
        ttk.Label(f, text='Key debounce (ms)').grid(row=4, column=0, sticky='w', pady=(8, 0))
        c = ttk.Combobox(f, textvariable=self.debounce, values=[str(x) for x in t.DEBOUNCE_OPTS], state='readonly', width=8)
        c.grid(row=4, column=1, pady=(8, 0))
        c.bind('<<ComboboxSelected>>', lambda e: self.setv(t.set_func, debounce=int(self.debounce.get())))
        ttk.Label(f, text='Sleep time').grid(row=5, column=0, sticky='w')
        sl = [self.sleep_label(s) for s in t.SLEEP_OPTS]
        c = ttk.Combobox(f, textvariable=self.sleep, values=sl, state='readonly', width=8)
        c.grid(row=5, column=1)
        c.bind('<<ComboboxSelected>>', lambda e: self.setv(t.set_func, sleep_s=t.SLEEP_OPTS[sl.index(self.sleep.get())]))
        ttk.Label(f, text='Lift-off distance (mm)').grid(row=6, column=0, sticky='w')
        c = ttk.Combobox(f, textvariable=self.lod, values=('1', '2'), state='readonly', width=8)
        c.grid(row=6, column=1)
        c.bind('<<ComboboxSelected>>', lambda e: self.setv(t.set_lod, int(self.lod.get())))
        ttk.Separator(f).grid(row=7, columnspan=4, sticky='ew', pady=8)
        ttk.Label(f, text='DPI light').grid(row=8, column=0, sticky='w')
        ttk.Combobox(f, textvariable=self.leffect, values=list(t.LIGHT_MODES), state='readonly', width=10).grid(row=8, column=1)
        ttk.Label(f, text='Brightness').grid(row=9, column=0, sticky='w')
        ttk.Combobox(f, textvariable=self.lbright, values=list(t.LIGHT_BRIGHT), state='readonly', width=10).grid(row=9, column=1)
        ttk.Label(f, text='Speed').grid(row=10, column=0, sticky='w')
        sp = ttk.Combobox(f, textvariable=self.lspeed, values=list(t.LIGHT_SPEED), state='readonly', width=10)
        sp.grid(row=10, column=1)
        ttk.Button(f, text='Apply light', command=lambda: self.setv(
            t.set_light, self.leffect.get(), t.LIGHT_BRIGHT[self.lbright.get()], t.LIGHT_SPEED[self.lspeed.get()],
            what='Light set')).grid(row=11, column=0, pady=6, sticky='w')

    # ------------------------------------------------------------ 6 config
    def build_config(self):
        f = self.tab('Config')
        self.profile = tk.IntVar(value=0)
        ttk.Label(f, text='Onboard config file').grid(row=0, column=0, sticky='w')
        for i in range(4):
            ttk.Radiobutton(f, text=str(i + 1), variable=self.profile, value=i,
                            command=lambda: self.setv(t.set_profile, self.profile.get(), what='Config switched')
                            ).grid(row=0, column=i + 1)
        ttk.Button(f, text='Export to file...', command=self.export).grid(row=1, column=0, pady=(14, 0), sticky='w')
        ttk.Button(f, text='Import from file...', command=self.import_).grid(row=1, column=1, columnspan=3, pady=(14, 0))
        ttk.Label(f, style='Muted.TLabel', wraplength=560, justify='left',
                  text='Export covers rate/DPI, buttons, shortcuts, parameters, macros (one JSON file you choose). '
                       'Import validates CRCs and only writes whitelisted addresses.').grid(row=2, columnspan=5, sticky='w', pady=8)

    def export(self):
        p = filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('JSON', '*.json')], title='Export config')
        if not p:
            return

        def w(d):
            cfg = t.export_config(d)
            with open(p, 'w', encoding='utf8') as fh:
                json.dump(cfg, fh, indent=1)
        self.bg(w, lambda _: self.status.set('Exported to %s' % p))

    def import_(self):
        p = filedialog.askopenfilename(filetypes=[('JSON', '*.json')], title='Import config')
        if not p:
            return
        try:
            with open(p, encoding='utf8') as fh:
                cfg = json.load(fh)
            bad = t.validate_config(cfg)
        except Exception as e:
            return messagebox.showerror('Import', str(e))
        if bad:
            return messagebox.showerror('Import', 'Invalid config: ' + '; '.join(bad))
        if messagebox.askyesno('Import', 'Write this configuration to the mouse?'):
            self.write_then_refresh(lambda d: t.import_config(d, cfg), 'Imported')

    # ------------------------------------------------------------ 7 other
    def build_other(self):
        f = self.tab('Other')
        self.other_txt = tk.StringVar()
        ttk.Label(f, textvariable=self.other_txt, justify='left').grid(row=0, column=0, columnspan=3, sticky='w')
        self.fw_txt = tk.StringVar()
        b = ttk.Button(f, text='Check for firmware update', command=self.fw_check)
        b.grid(row=3, column=0, pady=(14, 0), sticky='w')
        ttk.Label(f, textvariable=self.fw_txt, justify='left', wraplength=560).grid(row=4, columnspan=3, sticky='w')
        b = ttk.Button(f, text='Pair receiver...', command=self.pair)
        b.grid(row=1, column=0, pady=(14, 0), sticky='w')
        b = ttk.Button(f, text='Factory reset...', command=self.reset)
        b.grid(row=1, column=1, pady=(14, 0))
        ttk.Label(f, style='Muted.TLabel', wraplength=560, justify='left',
                  text='Receiver mode: dongle light / 4K RGB mode are shown read-only (value-to-label mapping unverified). '
                       'Firmware upgrade and USB upgrade mode are intentionally not implemented.').grid(row=2, columnspan=3, sticky='w', pady=8)

    def fw_check(self):
        cur = (self.r or {}).get('info', {}).get('fw')
        if not cur:
            self.fw_txt.set('The mouse has not been read yet: move it to wake it, press Refresh all, then try again.')
            return
        if not messagebox.askyesno('Firmware check', 'Send up to two requests to api-hub-cloud.atk.pro (vendor server)?\n'
                                   'They contain only VID/PID/model in the URL. Nothing else is sent.'):
            return
        self.fw_txt.set('Checking...')

        def run(cands):
            try:
                res = t.check_firmware(cur, candidates=cands)
            except BaseException:
                log_error('ERROR firmware check: ' + traceback.format_exc())
                res = dict(latest=None, newer=False, tried=[('check', 'internal error, see r1se_errors.log')])
            if not res['latest']:
                log_error('ERROR firmware check returned no version: %s' % (res['tried'],))
            if res['latest']:
                m = 'Current %s, latest %s: %s' % (cur, res['latest'], 'UPDATE AVAILABLE (install with the official ATK HUB)'
                                                  if res['newer'] else 'up to date' if res.get('comparable')
                                                  else 'versions not comparable, check manually')
                if res.get('url') != t.FW_URL % t.MOUSE_FW_ID:
                    m += ' (answer for the dongle IDs; it may be the dongle firmware)'
            else:
                m = 'No version returned. Tried: ' + '; '.join('%s -> %s' % x for x in res['tried'])
            self.q.put(lambda: self.fw_txt.set(m))

        def candidates(_):      # HID enumeration runs on the device worker (serialised with all device access)
            try:
                return t.firmware_candidates()
            except BaseException as e:      # incl. SystemExit from a missing hid module
                log_error('ERROR firmware check: %s' % e)
                return e

        def got(c):             # the network wait gets its own thread so device jobs are not blocked
            if isinstance(c, BaseException):
                self.fw_txt.set('Firmware check failed: %s' % c)
            else:
                threading.Thread(target=run, args=(c,), daemon=True).start()
        self.bg(candidates, got, 'Checking firmware...', need_dev=False)

    def pair(self):
        if messagebox.askyesno('Pair receiver', 'This starts wireless pairing (cmd 5, untested). The mouse may disconnect '
                               'until paired again. Continue?', icon='warning'):
            self.bg(lambda d: (lambda i: t.pair_receiver(d, i['cid'], i['mid']))(t.get_info(d)),
                    lambda _: self.status.set('Pairing started'))

    def reset(self):
        if messagebox.askyesno('Factory reset', 'This ERASES all settings and macros on the mouse. Continue?', icon='warning') and \
                messagebox.askyesno('Factory reset', 'Really reset to factory defaults?', icon='warning'):
            self.write_then_refresh(lambda d: t.factory_reset(d), 'Factory reset sent')


def main():
    sys.excepthook = lambda *a: log_error('CRASH ' + ''.join(traceback.format_exception(*a)))
    threading.excepthook = lambda a: log_error('CRASH (thread) ' + ''.join(
        traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback)))
    app = App()
    app.report_callback_exception = lambda *a: (log_error('ERROR (ui callback) ' + ''.join(
        traceback.format_exception(*a))), app.status.set('Error: %s' % a[1]))
    app.mainloop()


if __name__ == '__main__':
    main()
