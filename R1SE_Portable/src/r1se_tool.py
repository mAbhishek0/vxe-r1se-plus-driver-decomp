#!/usr/bin/env python3
"""VXE/ATK R1SE+ (COMPX protocol) library + CLI. Verified on hardware: see README.txt / PROTOCOL.md section 6.
Derived statically from ATK HUB filter-3fyXcGGg.js (see PROTOCOL.md).
Run:  python -I r1se_tool.py list | info | get-dpi | get-rate | set-dpi ... | set-rate ...
Writes are dry-run unless --apply is given.  pip install hidapi  (module name: hid)
"""
import argparse, json, os, re, sys, time

VIDS = (0x3554, 0x373B)
USAGE_PAGE, USAGE = 0xFF02, 0x0002   # vendor interface (report id 8, 16-byte in/out), verified on the 373B:1085 dongle
REPORT_ID = 8
CMD = dict(DOWNLOAD=1, BATTERY=4, SET_EEPROM=7, GET_EEPROM=8, RESTORE=9, STATUS_REPORT=10,
           GET_CFG=14, SET_CFG=15, CIDMID=16, VERSION=18, DONGLE_VERSION=29)
FORBIDDEN_CMDS = (13, 1, 90, 91)   # USB upgrade mode, firmware download data, upgrade notifies: refused by Dev.xfer
ADDR_RATE_BLOCK, ADDR_STAGE = 0, (12, 20, 28, 36)   # each stage addr = 2 stages x 4 bytes
MAX_STAGES = 2 * len(ADDR_STAGE)
RATE = {1000: 1, 500: 2, 250: 4, 125: 8, 2000: 16, 4000: 32, 8000: 64}
RATE_INV = {v: k for k, v in RATE.items()}
RATES_1K = (125, 250, 500, 1000)     # this mouse/dongle is 1 kHz max: only these are written
with open(os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__))),
                       'dpi_table_3395se.json')) as _f:
    TABLE = json.load(_f)            # [hexcode, dpi, has_double]
TABLE_HEX = {hx for hx, _, _ in TABLE}


def checksum(frame15):
    """Byte 15 of the 16-byte frame; the report id (8) is included in the sum."""
    return (85 - (REPORT_ID + sum(frame15))) & 0xFF


def build(cmd, addr=0, data=b'', length=None):
    assert len(data) <= 10
    f = bytearray(16)
    f[0] = cmd
    f[2] = (addr >> 8) & 255
    f[3] = addr & 255
    f[4] = len(data) if length is None else length
    f[5:5 + len(data)] = data
    f[15] = checksum(f[:15])
    return bytes(f)


def crc(*v):
    """Per-field / per-stage EEPROM CRC."""
    return (85 - sum(v)) & 0xFF


def dpi_decode(x, y, ex):
    """PAW3395SE (oe()). Unknown hex codes decode to None."""
    def one(h, dbl):
        for hx, t, d in TABLE:
            if hx == h:
                return 2 * t if (dbl and d) else t
        return None
    return one(x, ex & 2), one(y, ex & 32)


def dpi_encode(x, y):
    """PAW3395SE (ne()). The table has 50 DPI steps up to 10000 and 100 DPI steps above."""
    def one(v):
        v = 50 * round(v / 50) if v <= 10000 else 100 * round(v / 100)
        for hx, t, d in TABLE:
            if t == v:
                return hx, 0
            if d and 2 * t == v:
                return hx, 1
        raise ValueError('unsupported DPI %d' % v)
    hx, dx = one(x)
    hy, dy = one(y)
    return hx, hy, (2 if dx else 0) | (32 if dy else 0)


def import_hid():
    try:
        import hid
        return hid
    except ImportError:
        sys.exit('pip install hidapi')


def find(hid, pid=None):
    return [d for d in hid.enumerate()
            if d['vendor_id'] in VIDS and d['usage_page'] == USAGE_PAGE and d['usage'] == USAGE
            and (pid is None or d['product_id'] == pid)]


class Dev:
    def __init__(self, pid=None, timeout=3.0, retries=3, rid_in=True, dry=False):
        self.dry = dry          # dry-run: writes are printed, not sent
        self.hid = import_hid()
        c = find(self.hid, pid)
        if not c:
            sys.exit('no VXE/ATK vendor interface (VID 3554/373B, UP FF02 U 02) found')
        self.timeout, self.retries, self.rid_in = timeout, retries, rid_in
        self.h = self.hid.device()
        self.h.open_path(c[0]['path'])
        if pid is None and len(c) > 1:
            # wired mouse and dongle both present: use the one whose mouse actually answers
            # (the dongle stays silent while the mouse is on the cable)
            probe = build(CMD['VERSION'])
            self.timeout, self.retries = 1.5, 0
            try:
                for cand in c:
                    self.h.close()
                    self.h = self.hid.device()
                    self.h.open_path(cand['path'])
                    try:
                        self.xfer(probe)
                        break
                    except TimeoutError:
                        continue
                else:
                    raise TimeoutError('none of the %d VXE/ATK interfaces answered (move the mouse to wake it, then retry)'
                                       % len(c))
            except BaseException:
                self.close()        # no handle is leaked when the probe fails (timeout or I/O error)
                raise
            self.timeout, self.retries = timeout, retries

    def close(self):
        try:
            self.h.close()
        except Exception:
            pass

    def xfer(self, frame):
        if frame[0] in FORBIDDEN_CMDS:
            raise PermissionError('command %d is blocked (firmware/upgrade path)' % frame[0])
        addressed = frame[0] in (CMD['SET_EEPROM'], CMD['GET_EEPROM'])
        for _ in range(self.retries + 1):
            self.h.set_nonblocking(1)       # read(n, 0) would block forever in python-hidapi
            while self.h.read(64):          # drop late replies / status reports left over from earlier requests
                pass
            self.h.set_nonblocking(0)
            self.h.write(bytes([REPORT_ID]) + frame)
            end = time.time() + self.timeout
            while time.time() < end:
                r = bytes(self.h.read(64, 100))
                if not r:
                    continue
                if self.rid_in and len(r) > 1 and r[0] == REPORT_ID and r[1] == frame[0]:
                    r = r[1:]               # strip numbered-report id
                if r[0] != frame[0]:
                    continue
                if addressed and r[2:5] != frame[2:5]:
                    continue                # stale reply to an earlier EEPROM request: keep waiting
                return r
        raise TimeoutError('no response for cmd %d' % frame[0])

    def eeprom(self, addr, n):
        return self.xfer(build(CMD['GET_EEPROM'], addr, length=n))[5:5 + n]

    def eeprom_w(self, addr, data):
        assert 0 <= addr < 0x2000 and len(data) <= 10
        if self.dry:
            print('DRY write addr=%d %s' % (addr, bytes(data).hex()))
            return b''
        return self.xfer(build(CMD['SET_EEPROM'], addr, bytes(data)))

    def eeprom_big(self, addr, n):
        out = b''
        while n > 0:
            k = min(10, n)
            out += bytes(self.eeprom(addr + len(out), k))
            n -= k
        return out

    def eeprom_w_big(self, addr, data, verify=True):
        """Chunked write (10 B per frame); each chunk is read back and re-sent up to 3x if it did not stick."""
        data = bytes(data)
        for i in range(0, len(data), 10):
            ch = data[i:i + 10]
            for _ in range(3):
                self.eeprom_w(addr + i, ch)
                if not self.dry:
                    time.sleep(0.12)       # flash-backed areas need settle time before readback
                if self.dry or not verify or bytes(self.eeprom(addr + i, len(ch))) == ch:
                    break
            else:
                raise IOError('write verify failed at %d' % (addr + i))

    def eeprom_stream_w(self, addr, data, tries=3):
        """Macro-area write: the firmware only accepts it as one uninterrupted stream of 10-byte frames starting at
        the slot base (as the vendor app does). No per-frame read-back or resend (a resent frame is appended and corrupts
        the slot); verify once at the end and on mismatch redo the whole stream from the base."""
        data = bytes(data)
        data += bytes(-len(data) % 10)
        for _ in range(tries):
            for i in range(0, len(data), 10):
                self.eeprom_w(addr + i, data[i:i + 10])
            if self.dry:
                return
            time.sleep(0.2)
            if bytes(self.eeprom_big(addr, len(data))) == data:
                return
        raise IOError('macro write verify failed at %d' % addr)

    def cmd(self, c, data=b'', length=None):
        """Read-type command (no side effects expected)."""
        return self.xfer(build(c, 0, data, length))

    def cmd_w(self, c, data=b'', length=None):
        """Write-type command; honours dry-run."""
        if c in FORBIDDEN_CMDS:
            raise PermissionError('command %d is blocked (firmware/upgrade path)' % c)
        if self.dry:
            print('DRY cmd %d data=%s' % (c, bytes(data).hex()))
            return b''
        return self.xfer(build(c, 0, data, length))



# ---------------------------------------------------------------- high-level API
# Status legend (see README): V = verified on hardware, I = implemented from vendor code, untested, U = unverified (never auto-written)
A_FUNC, A_SENSOR, A_ANGLE, A_LOD, A_LIGHT = 169, 181, 189, 10, 76
A_KEY0, A_SHORT0, A_MACRO0 = 96, 256, 768
BUTTONS = ['Left', 'Right', 'Middle', 'Back (side 1)', 'Advance (side 2)', 'DPI cycle']
DEBOUNCE_OPTS = (0, 1, 2, 4, 8, 15, 20)                   # ms (list from vendor UI; addr/encoding from vendor code)
SLEEP_OPTS = (30, 60, 120, 180, 300, 1200, 1500, 1800)    # seconds (stored byte = s/10)
LIGHT_MODES = {'Close': 0, 'Always On': 1, 'Breathing': 2}
LIGHT_BRIGHT = {'Min': 16, 'Medium': 128, 'Max': 255}
LIGHT_SPEED = {'Slow': 1, 'Medium': 3, 'Fast': 5}          # vendor code only defines these three codes
SENSOR_MODES = {'Daily Work (Basic)': 0, 'Game Competitive (ATK Shard)': 1}   # 2 = "Competitive Max" (needs corded fw): not offered


def chk_pairs(raw, n):
    """raw = [v,crc]*n ; return (values, all_crc_ok)."""
    vals = [raw[2 * i] for i in range(n)]
    ok = all(raw[2 * i + 1] == crc(raw[2 * i]) for i in range(n))
    return vals, ok


def pairs(*vals):
    out = bytearray()
    for v in vals:
        out += bytes([v & 255, crc(v)])
    return out


# ---- info
def get_info(d):
    r = d.cmd(CMD['VERSION'])
    fw = '%x.%02x' % (r[5], r[6])
    r = d.cmd(CMD['CIDMID'])
    cm = (r[5], r[6])
    r = d.cmd(CMD['BATTERY'])
    bat = dict(percent=r[5], charging=bool(r[6]), mv=(r[7] << 8) | r[8])
    try:
        r = d.cmd(CMD['DONGLE_VERSION'])
        dv = '%x.%02x' % (r[5], r[6])
    except TimeoutError:
        dv = None
    return dict(fw=fw, cid=cm[0], mid=cm[1], battery=bat, dongle_fw=dv)


def get_online(d):
    return d.cmd(3)[5] == 1


# ---- rate / dpi
def get_rate(d):
    b = rate_block(d)
    return RATE_INV.get(b[0]), b[1] == crc(b[0])


def need_crc(raw, offsets, what):
    """Read-modify-write guard: refuse when a [value, crc] field that would be written back unchanged has a bad CRC
    (garbled or stale read) instead of re-stamping it with a fresh CRC."""
    for i in offsets:
        if raw[i + 1] != crc(raw[i]):
            raise IOError('%s: field at +%d read back with a bad CRC; nothing written (retry)' % (what, i))


def set_rate(d, hz):
    if hz not in RATES_1K:
        raise ValueError('rate must be one of %s Hz' % (RATES_1K,))
    b = rate_block(d)
    need_crc(b, (2, 4), 'rate block')
    b[0], b[1] = RATE[hz], crc(RATE[hz])
    d.eeprom_w(ADDR_RATE_BLOCK, b)


def get_dpi(d):
    b = rate_block(d)
    stages = []
    for ad in ADDR_STAGE:
        raw = d.eeprom(ad, 8)
        for i in range(2):
            x, y, ex, c = raw[4 * i:4 * i + 4]
            stages.append(dpi_decode(x, y, ex))
    return dict(count=b[2], current=b[4], stages=stages)


def set_dpi_stage(d, n, x, y):
    if not 0 <= n < MAX_STAGES:
        raise ValueError('stage 0..%d' % (MAX_STAGES - 1))
    hx, hy, ex = dpi_encode(x, y)
    base = ADDR_STAGE[n // 2]
    raw = bytearray(d.eeprom(base, 8))
    o = 4 * (n % 2)
    p = 4 - o                       # the other stage in this 8-byte block is written back unchanged
    if raw[p + 3] != crc(*raw[p:p + 3]):
        raise IOError('DPI stage %d read back with a bad CRC; nothing written (retry)' % (n ^ 1))
    raw[o:o + 4] = bytes([hx, hy, ex, crc(hx, hy, ex)])
    d.eeprom_w(base, raw)


def set_dpi_current(d, n):
    b = rate_block(d)
    need_crc(b, (0, 2), 'rate block')
    if not 0 <= n < min(b[2], MAX_STAGES):
        raise ValueError('active stage must be 0..%d (the mouse has %d stages)' % (min(b[2], MAX_STAGES) - 1, b[2]))
    b[4], b[5] = n, crc(n)
    d.eeprom_w(ADDR_RATE_BLOCK, b)


# ---- parameters (function block @169, LOD @10, sensor @181, far distance, DPI light @76)
def get_func(d):
    v, ok = chk_pairs(d.eeprom(A_FUNC, 10), 5)
    return dict(debounce=v[0], motion_sync=v[1], sleep_s=v[2] * 10, line_corr=v[3], ripple=v[4], crc_ok=ok)


def set_func(d, **kw):
    """Read-modify-write of the 10-byte block (same layout the vendor app writes)."""
    raw = d.eeprom(A_FUNC, 10)
    v, _ = chk_pairs(raw, 5)
    keys = ('debounce', 'motion_sync', 'sleep_s', 'line_corr', 'ripple')
    need_crc(raw, [2 * i for i, k in enumerate(keys) if k not in kw], 'function block')
    cur = dict(debounce=v[0], motion_sync=v[1], sleep_s=v[2] * 10, line_corr=v[3], ripple=v[4])
    cur.update(kw)
    if cur['debounce'] not in DEBOUNCE_OPTS:
        raise ValueError('debounce must be one of %s' % (DEBOUNCE_OPTS,))
    if cur['sleep_s'] not in SLEEP_OPTS:
        raise ValueError('sleep must be one of %s s' % (SLEEP_OPTS,))
    for k in ('motion_sync', 'line_corr', 'ripple'):
        if cur[k] not in (0, 1):
            raise ValueError(k + ' must be 0/1')
    d.eeprom_w(A_FUNC, pairs(cur['debounce'], cur['motion_sync'], cur['sleep_s'] // 10, cur['line_corr'], cur['ripple']))


def get_lod(d):
    v, ok = chk_pairs(d.eeprom(A_LOD, 2), 1)
    return v[0], ok


def set_lod(d, mm):
    if mm not in (1, 2):
        raise ValueError('LOD 1 or 2 mm')
    d.eeprom_w(A_LOD, pairs(mm))


def get_sensor_mode(d):
    v, ok = chk_pairs(d.eeprom(A_SENSOR, 6), 3)
    return dict(sleep_enabled=v[0], sleep_s=v[1] * 10, mode=v[2], crc_ok=ok)


def set_sensor_mode(d, mode):
    if mode not in (0, 1):
        raise ValueError('mode 0 (basic) or 1 (competitive)')
    raw = d.eeprom(A_SENSOR, 6)
    need_crc(raw, (0, 2), 'sensor block')
    d.eeprom_w(A_SENSOR, pairs(raw[0], raw[2], mode))


def get_far(d):
    return d.cmd(23)[5]


def set_far(d, on):
    d.cmd_w(22, bytes([1 if on else 0]), 10)


def get_light(d):
    v, ok = chk_pairs(d.eeprom(A_LIGHT, 8), 4)
    mode, br, sp, en = v
    name = 'Close' if not en else {1: 'Always On', 2: 'Breathing'}.get(mode, '?')
    return dict(effect=name, brightness=br, speed=sp, enabled=en, raw_mode=mode, crc_ok=ok)


def set_light(d, effect, brightness, speed):
    if brightness not in LIGHT_BRIGHT.values() or speed not in LIGHT_SPEED.values() or effect not in LIGHT_MODES:
        raise ValueError('bad light parameter')
    mode = LIGHT_MODES[effect]
    if not mode:                    # "Close" keeps the old mode code and clears the enable byte
        raw = d.eeprom(A_LIGHT, 8)
        need_crc(raw, (0,), 'light block')
        mode = raw[0] if raw[0] in (1, 2) else 2
    d.eeprom_w(A_LIGHT, pairs(mode, brightness, speed, 0 if effect == 'Close' else 1))


# ---- profiles / config
def get_profile(d):
    return d.cmd(CMD['GET_CFG'])[5]


def set_profile(d, n):
    if not 0 <= n <= 3:
        raise ValueError('profile 0..3')
    d.cmd_w(CMD['SET_CFG'], bytes([n]), 1)


# ---- buttons
def get_buttons(d):
    out = []
    for k in range(3):
        raw = d.eeprom(A_KEY0 + 8 * k, 8)
        for i in range(2):
            c, v1, v2, cc = raw[4 * i:4 * i + 4]
            out.append((c, v1, v2, cc == crc(c, v1, v2)))
    return out


def button_lockout(idx, cls, v1):
    """True if this assignment would disable Left (0) or Right (1): class 0 (off) or class 1 with no mouse bit."""
    return idx in (0, 1) and (cls == 0 or (cls == 1 and v1 == 0))


def is_click(cls, v1):
    """Entry that produces a primary (left or right) mouse click."""
    return cls == 1 and v1 & 3 != 0


def button_entry_ok(cls, v1, v2):
    """Only the classes/values this tool offers (action_catalog, keyboard/multimedia shortcuts, macros)."""
    if cls == 5:
        return v1 == 0 and v2 == 0
    if cls == 6:
        return 0 <= v1 < MACRO_SLOTS and 1 <= v2 <= 255      # v2: 1 once, 253/254/255 modes, N = count
    allowed = {1: (0, 1, 2, 4, 8, 16), 2: (1, 2, 3), 3: (1, 2), 9: (161, 162, 163, 164, 255), 11: (1, 2)}
    return cls in allowed and v1 in allowed[cls] and v2 == 0


LOCKOUT_MSG = 'blocked: Left/Right cannot be disabled and at least one of them must stay a mouse click (lock-out protection)'


def check_button(d, idx, cls, v1=0, v2=0):
    """Raise ValueError unless the assignment is allowed. For Left/Right a non-click assignment also needs the other
    of the two to be a (CRC-valid) mouse click on the device."""
    if not (0 <= idx < 6 and button_entry_ok(cls, v1, v2)):
        raise ValueError('bad button assignment')
    if button_lockout(idx, cls, v1):
        raise ValueError(LOCKOUT_MSG)
    if idx in (0, 1) and not is_click(cls, v1):
        raw = d.eeprom(A_KEY0, 8)
        c, a, b, ck = raw[4 * (1 - idx):8 - 4 * idx]
        if ck != crc(c, a, b) or not is_click(c, a):
            raise ValueError(LOCKOUT_MSG)


def _write_button(d, idx, cls, v1, v2):
    d.eeprom_w(A_KEY0 + 4 * idx, bytes([cls, v1, v2, crc(cls, v1, v2)]))


def set_button(d, idx, cls, v1=0, v2=0):
    check_button(d, idx, cls, v1, v2)
    _write_button(d, idx, cls, v1, v2)


MOD_BITS = {'Ctrl': 1, 'Shift': 2, 'Alt': 4, 'Win': 8, 'RCtrl': 16, 'RShift': 32, 'RAlt': 64, 'RWin': 128}
KEYS = {}
for _i, _c in enumerate('ABCDEFGHIJKLMNOPQRSTUVWXYZ'):
    KEYS[_c] = 4 + _i
for _i, _c in enumerate('1234567890'):
    KEYS[_c] = 30 + _i
KEYS.update({'Enter': 40, 'Esc': 41, 'Backspace': 42, 'Tab': 43, 'Space': 44, '-': 45, '=': 46, '[': 47, ']': 48,
             '\\': 49, ';': 51, "'": 52, '`': 53, ',': 54, '.': 55, '/': 56, 'CapsLock': 57})
for _i in range(12):
    KEYS['F%d' % (_i + 1)] = 58 + _i
KEYS.update({'PrintScreen': 70, 'ScrollLock': 71, 'Pause': 72, 'Insert': 73, 'Home': 74, 'PageUp': 75, 'Delete': 76,
             'End': 77, 'PageDown': 78, 'Right': 79, 'Left': 80, 'Down': 81, 'Up': 82, 'NumLock': 83,
             'Num/': 84, 'Num*': 85, 'Num-': 86, 'Num+': 87, 'NumEnter': 88, 'Num.': 99})
for _i in range(9):
    KEYS['Num%d' % (_i + 1)] = 89 + _i
KEYS['Num0'] = 98

T_MOD, T_GEN, T_MEDIA = 0, 1, 2     # shortcut-entry key types
DOWN, UP = 0, 1


def _media(v1, v2=0):
    return [(T_MEDIA, DOWN, v1, v2), (T_MEDIA, UP, v1, v2)]


SYSTEM = {
    'Mouse & Keyboard': [('Disable', 1, 0, 0), ('Left', 1, 1, 0), ('Right', 1, 2, 0), ('Middle', 1, 4, 0),
                         ('Back', 1, 8, 0), ('Forward', 1, 16, 0)],
    'Config File': [('Switch to config 1', 9, 161, 0), ('Switch to config 2', 9, 162, 0),
                    ('Switch to config 3', 9, 163, 0), ('Switch to config 4', 9, 164, 0), ('Cycle configs', 9, 255, 0)],
    'DPI Key': [('DPI cycle', 2, 1, 0), ('DPI +', 2, 2, 0), ('DPI -', 2, 3, 0)],
    'Mouse Wheel': [('Roll left', 3, 1, 0), ('Roll right', 3, 2, 0), ('Wheel up', 11, 1, 0), ('Wheel down', 11, 2, 0)],
}
MULTIMEDIA = [('Brightness +', 111, 0), ('Brightness -', 112, 0), ('Media player', 131, 1), ('Stop', 183, 0),
              ('Play/Pause', 205, 0), ('Previous track', 182, 0), ('Next track', 181, 0), ('Mute', 226, 0),
              ('Volume +', 233, 0), ('Volume -', 234, 0), ('Mail', 138, 1), ('Homepage', 35, 2), ('Search', 33, 2),
              ('Refresh', 39, 2), ('Favorites', 42, 2), ('Stop loading', 38, 2), ('Web forward', 37, 2),
              ('Web back', 36, 2), ('Calculator', 146, 1), ('My computer', 148, 1)]


def action_catalog():
    """{category: {label: spec}} ; spec = ('key',cls,v1,v2) | ('short',[(type,state,v1,v2),..])"""
    cat = {'System/' + k: {n: ('key', c, a, b) for n, c, a, b in v} for k, v in SYSTEM.items()}
    cat['System/Multimedia'] = {n: ('short', _media(a, b)) for n, a, b in MULTIMEDIA}
    return cat


def key_actions(key, mods=()):
    """Keyboard key (+ modifiers). With modifiers the order is [mods down, key down, mods up, key up] (what the vendor's
    decoder expects); verified on hardware (Ctrl+A, Ctrl+Shift+Esc)."""
    code = KEYS[key]
    if not mods:
        return [(T_GEN, DOWN, code, 0), (T_GEN, UP, code, 0)]
    m = [MOD_BITS[x] for x in mods]
    return ([(T_MOD, DOWN, b, 0) for b in m] + [(T_GEN, DOWN, code, 0)] +
            [(T_MOD, UP, b, 0) for b in reversed(m)] + [(T_GEN, UP, code, 0)])


def _act_bytes(a):
    t, st, v1, v2 = a
    return bytes([t | (0x80 if st == DOWN else 0x40), v1, v2])


def shortcut_encode(actions):
    body = b''.join(_act_bytes(a) for a in actions)
    assert len(actions) * 3 + 2 <= 32
    ck = (85 - (len(actions) + sum(body))) & 255
    return bytes([len(actions)]) + body + bytes([ck])


def shortcut_decode(raw):
    n = raw[0]
    if n == 0 or n > 10 or len(raw) < 1 + 3 * n + 1:
        return None
    acts = []
    for i in range(n):
        b0, v1, v2 = raw[1 + 3 * i:4 + 3 * i]
        acts.append((b0 & 7, UP if b0 & 0x40 else DOWN, v1, v2))
    ok = raw[1 + 3 * n] == (85 - (n + sum(raw[1:1 + 3 * n]))) & 255
    return acts if ok else None


def get_shortcut(d, idx):
    return shortcut_decode(d.eeprom_big(A_SHORT0 + 32 * idx, 32))


def set_shortcut(d, idx, actions):
    """Writes the action list, then points the button at it (class 5). Validated before anything is written."""
    check_button(d, idx, 5, 0, 0)
    data = shortcut_encode(actions)
    d.eeprom_w_big(A_SHORT0 + 32 * idx, data)
    _write_button(d, idx, 5, 0, 0)


def describe_button(entry, short=None):
    c, v1, v2, ok = entry
    for cat, items in action_catalog().items():
        for n, sp in items.items():
            if sp[0] == 'key' and sp[1:] == (c, v1, v2):
                return '%s: %s' % (cat.replace('System/', ''), n)
    if c == 0:
        return 'Disabled'
    if c == 4:
        return 'Fire key (interval=%d, count=%d)' % (v1, v2)
    if c == 6:
        return 'Macro M%d (mode %d)' % (v1 + 1, v2)
    if c == 5:
        if short:
            for n, a, b in MULTIMEDIA:
                if short == _media(a, b):
                    return 'Multimedia: ' + n
            rev = {v: k for k, v in KEYS.items()}
            gen = [x for x in short if x[0] == T_GEN and x[1] == DOWN]
            mods = [k for k, bit in MOD_BITS.items() if any(x[0] == T_MOD and x[1] == DOWN and x[2] == bit for x in short)]
            if gen:
                return 'Keyboard: ' + '+'.join(mods + [rev.get(gen[0][2], '0x%02x' % gen[0][2])])
        return 'Shortcut (unreadable)'
    return 'Class %d (%d,%d)' % (c, v1, v2)


def apply_action(d, idx, spec):
    if spec[0] == 'key':
        set_button(d, idx, spec[1], spec[2], spec[3])
    else:
        set_shortcut(d, idx, spec[1])


DEFAULT_BUTTONS = [(1, 1, 0), (1, 2, 0), (1, 4, 0), (1, 8, 0), (1, 16, 0), (2, 1, 0)]


def restore_default_buttons(d):
    for i, (c, a, b) in enumerate(DEFAULT_BUTTONS):
        set_button(d, i, c, a, b)


# ---- macros (slot k: base 768+384k; layout from vendor setMacro/getMacro/_resetMacro)
MACRO_SLOTS = 12
MACRO_HDR = bytes([8] + [2] * 8 + [255] * 22)   # 31 bytes; count byte at +31, 5-byte actions from +32, then crc
MACRO_MAX = 69      # 32 + 5*69 + 1 = 378 B, zero-padded to 380 <= 384 B slot: the stream never touches the next slot


def macro_base(k):
    return A_MACRO0 + 384 * k


def macro_encode(actions):
    """actions: list of (keytype, state, value1, value2, delay) ; state DOWN/UP; delay = u16 in ms (verified)."""
    if not 1 <= len(actions) <= MACRO_MAX:
        raise ValueError('1..%d actions' % MACRO_MAX)
    body = b''
    for t, st, v1, v2, dl in actions:
        if not 0 <= dl <= 65535:
            raise ValueError('delay must be 0..65535 ms')
        body += _act_bytes((t, st, v1, v2)) + bytes([(dl >> 8) & 255, dl & 255])
    ck = (85 - (len(actions) + sum(body))) & 255
    return MACRO_HDR + bytes([len(actions)]) + body + bytes([ck])


def macro_get(d, k):
    n = d.eeprom(macro_base(k) + 31, 1)[0]
    if n == 0 or n > MACRO_MAX:
        return None
    raw = d.eeprom_big(macro_base(k) + 32, 5 * n + 1)
    acts = []
    for i in range(n):
        b0, v1, v2, h, l = raw[5 * i:5 * i + 5]
        acts.append((b0 & 7, UP if b0 & 0x40 else DOWN, v1, v2, (h << 8) | l))
    ok = raw[5 * n] == (85 - (n + sum(raw[:5 * n]))) & 255
    return dict(actions=acts, crc_ok=ok)


def macro_set(d, k, actions):
    if not 0 <= k < MACRO_SLOTS:
        raise ValueError('macro slot 0..%d' % (MACRO_SLOTS - 1))
    d.eeprom_stream_w(macro_base(k), macro_encode(actions))


def macro_delete(d, k):
    if not 0 <= k < MACRO_SLOTS:
        raise ValueError('macro slot 0..%d' % (MACRO_SLOTS - 1))
    d.eeprom_stream_w(macro_base(k), MACRO_HDR + b'\x00')       # vendor _resetMacro payload


def assign_macro(d, idx, k, mode=1):
    """v2 codes from vendor setKey: 254 stop immediately, 253 repeat until next press, 255 repeat until any mouse
    button, 1 = run once (1, 253 and 255 verified on hardware)."""
    if not 0 <= k < MACRO_SLOTS:
        raise ValueError('macro slot 0..%d' % (MACRO_SLOTS - 1))
    set_button(d, idx, 6, k, mode)


def macro_from_text(text):
    """Tiny DSL: 'A+ A- @50 B+ B-' ; KEY+ = down, KEY- = up, @N sets the delay in ms for following steps (default 10)."""
    out, delay = [], 10
    for tok in text.split():
        if tok.startswith('@'):
            if not tok[1:].isdigit() or int(tok[1:]) > 65535:
                raise ValueError('bad delay %r (use @0..@65535 ms)' % tok)
            delay = int(tok[1:])
            continue
        st = DOWN if tok.endswith('+') else UP if tok.endswith('-') else None
        name = tok[:-1]
        if st is None or name not in KEYS:
            raise ValueError('bad token %r (use KEY+ / KEY- / @ms)' % tok)
        out.append((T_GEN, st, KEYS[name], 0, delay))
    return out


def macro_to_text(acts):
    rev = {v: k for k, v in KEYS.items()}
    return ' '.join('%s%s' % (rev.get(v1, '0x%02x' % v1), '+' if st == DOWN else '-') if t == T_GEN
                    else '?%d%s' % (v1, '+' if st == DOWN else '-') for t, st, v1, v2, dl in acts)


# ---- config export / import (JSON; caller supplies the path)
LEGACY_BLOCKS = (44, 52, 60, 68)    # DPI stage colours: exported by older builds, never written (no colour UI)


def _regions():
    r = [(0, 10), (10, 2), (12, 8), (20, 8), (28, 8), (36, 8), (76, 8),
         (96, 8), (104, 8), (112, 8), (169, 10), (181, 6)]
    for k in range(6):
        r.append((A_SHORT0 + 32 * k, 32))
    return r


def export_config(d):
    cfg = dict(format='r1se-config-v1', blocks={}, macros={}, far_distance=get_far(d), profile=get_profile(d),
               info=get_info(d))
    for a, n in _regions():
        cfg['blocks'][str(a)] = d.eeprom_big(a, n).hex()
    for k in range(MACRO_SLOTS):
        n = d.eeprom(macro_base(k) + 31, 1)[0]
        if 0 < n <= MACRO_MAX:
            cfg['macros'][str(k)] = d.eeprom_big(macro_base(k), 32 + 5 * n + 1).hex()
    return cfg


def _pairs_ok(raw, n):
    return all(raw[2 * i + 1] == crc(raw[2 * i]) for i in range(n))


def _check_block(a, raw, blocks):
    """Problem string for one whitelisted block, or None. Same value whitelists as the setters."""
    if a == ADDR_RATE_BLOCK:
        if not (_pairs_ok(raw, 3) and raw[0] in [RATE[h] for h in RATES_1K] and 1 <= raw[2] <= MAX_STAGES
                and raw[4] < raw[2]):
            return 'bad rate block (rate 125..1000 Hz, 1..%d stages, active < count, CRCs)' % MAX_STAGES
        if not (raw[6:10] == bytes(4) or _pairs_ok(raw[6:10], 2)):
            return 'bad rate block bytes 6-9 (button operation mode): must be zero or valid [value, crc] pairs'
    elif a == A_LOD:
        if not (_pairs_ok(raw, 1) and raw[0] in (1, 2)):
            return 'bad lift-off block (1 or 2 mm)'
    elif a in ADDR_STAGE:
        for i in range(2):
            x, y, ex, c = raw[4 * i:4 * i + 4]
            if not (x in TABLE_HEX and y in TABLE_HEX and ex & ~0x22 == 0 and c == crc(x, y, ex)):
                return 'bad DPI stage %d' % (2 * ADDR_STAGE.index(a) + i + 1)
    elif a in (A_KEY0, A_KEY0 + 8, A_KEY0 + 16):
        for i in range(2):
            idx = (a - A_KEY0) // 4 + i
            c, v1, v2, ck = raw[4 * i:4 * i + 4]
            if ck != crc(c, v1, v2) or not button_entry_ok(c, v1, v2):
                return 'bad button entry (%s)' % BUTTONS[idx]
            if button_lockout(idx, c, v1):
                return '%s button would be disabled (blocked)' % BUTTONS[idx]
        if a == A_KEY0 and not (is_click(raw[0], raw[1]) or is_click(raw[4], raw[5])):
            return 'neither Left nor Right would stay a mouse click (blocked)'
    elif a == A_FUNC:
        if not (_pairs_ok(raw, 5) and raw[0] in DEBOUNCE_OPTS and raw[4] * 10 in SLEEP_OPTS
                and all(raw[i] in (0, 1) for i in (2, 6, 8))):
            return 'bad function block (debounce/sleep/toggles)'
    elif a == A_SENSOR:
        if not (_pairs_ok(raw, 3) and raw[4] in (0, 1)):
            return 'bad sensor block (mode must be 0 or 1)'
    elif a == A_LIGHT:
        if not (_pairs_ok(raw, 4) and raw[0] in LIGHT_MODES.values() and raw[2] in LIGHT_BRIGHT.values()
                and raw[4] in LIGHT_SPEED.values() and raw[6] in (0, 1)):
            return 'bad DPI light block'
    elif A_SHORT0 <= a < A_SHORT0 + 32 * 6:
        k = (a - A_SHORT0) // 32
        keys = blocks.get(str(A_KEY0 + 8 * (k // 2)))
        try:
            uses = bytes.fromhex(keys)[4 * (k % 2)] == 5
        except (TypeError, ValueError, IndexError):
            uses = False
        if uses and shortcut_decode(raw) is None:
            return 'bad shortcut for %s' % BUTTONS[k]
    return None


def validate_config(cfg):
    """Return list of problems (empty = ok). Only whitelisted addresses/lengths with valid CRCs and values the setters
    would accept are allowed."""
    if not isinstance(cfg, dict) or cfg.get('format') != 'r1se-config-v1':
        return ['not an r1se-config-v1 file']
    blocks, macros = cfg.get('blocks', {}), cfg.get('macros', {})
    if not isinstance(blocks, dict) or not isinstance(macros, dict):
        return ['blocks/macros must be objects']
    bad = []
    allowed = dict(_regions())
    for a, h in blocks.items():
        try:
            if not isinstance(h, str):
                raise ValueError
            a_i, raw = int(a), bytes.fromhex(h)
        except ValueError:
            bad.append('bad block %s' % a)
            continue
        if a != str(a_i):               # e.g. '096' next to '96': one address, one canonical key
            bad.append('bad block key %r' % a)
            continue
        if a_i in LEGACY_BLOCKS and len(raw) == 8:
            continue
        if a_i not in allowed or len(raw) != allowed[a_i]:
            bad.append('unexpected block %s' % a)
            continue
        p = _check_block(a_i, raw, blocks)
        if p:
            bad.append(p)
    for k, h in macros.items():
        try:
            raw = bytes.fromhex(h) if isinstance(h, str) else b''
            n = raw[31]
            ok = (0 <= int(k) < MACRO_SLOTS and 0 < n <= MACRO_MAX and len(raw) == 33 + 5 * n
                  and raw[:31] == MACRO_HDR and raw[-1] == (85 - (n + sum(raw[32:-1]))) & 255
                  and all(raw[32 + 5 * i] & 0xC0 in (0x80, 0x40) and not raw[32 + 5 * i] & 0x38 for i in range(n)))
        except (ValueError, IndexError):
            ok = False
        if not ok:
            bad.append('bad macro %s' % k)
    if cfg.get('far_distance') not in (None, 0, 1):
        bad.append('bad far_distance')
    return bad


def _import_writes(cfg):
    """[(addr, bytes)] the import would write: legacy colour blocks and shortcut slots no button uses (if they do
    not decode) are skipped."""
    out = []
    for a, h in cfg.get('blocks', {}).items():
        a_i, raw = int(a), bytes.fromhex(h)
        if a_i in LEGACY_BLOCKS:
            continue
        if A_SHORT0 <= a_i < A_SHORT0 + 32 * 6 and shortcut_decode(raw) is None:
            continue
        out.append((a_i, raw))
    return out


def import_config(d, cfg, include_macros=True):
    bad = validate_config(cfg)
    if bad:
        raise ValueError('; '.join(bad))
    writes = _import_writes(cfg)
    for i, (a, raw) in enumerate(writes):
        if a == ADDR_RATE_BLOCK:
            # bytes 6-9 (bhop / button operation mode) are never changed by an import: the file must hold zeros or
            # the device's current bytes, and the device's bytes are written back
            cur = bytes(rate_block(d))[6:10]
            if not (cur == bytes(4) or _pairs_ok(cur, 2)):
                raise IOError('rate block bytes 6-9 read back with a bad CRC; nothing written (retry)')
            if raw[6:10] not in (bytes(4), cur):
                raise ValueError('rate block bytes 6-9 differ from the mouse (%s vs %s); nothing written'
                                 % (raw[6:10].hex(), cur.hex()))
            writes[i] = (a, raw[:6] + cur)
    for a, raw in writes:
        d.eeprom_w_big(a, raw)
    if include_macros:
        for k, h in cfg.get('macros', {}).items():
            d.eeprom_stream_w(macro_base(int(k)), bytes.fromhex(h))
    if cfg.get('far_distance') in (0, 1):
        set_far(d, cfg['far_distance'])


# ---- other
def pair_receiver(d, cid, mid):
    """cmd 5 (SetWirelessDonglePair). NEVER run by the test-suite; GUI/CLI require explicit confirmation."""
    d.cmd_w(5, bytes([cid, mid]), 2)


def pair_result(d):
    r = d.cmd(6)
    return dict(status=r[5], seconds_left=r[6])


def factory_reset(d):
    """cmd 9 + vendor's macro wipe. DESTRUCTIVE; GUI/CLI require confirmation. The vendor _resetMacro wipes 16 slots
    (macro0..15, up to addr 6912); only the 12 slots this tool whitelists (768..5375) are wiped here."""
    d.cmd_w(CMD['RESTORE'])
    for k in range(MACRO_SLOTS):
        macro_delete(d, k)


def get_dongle_light(d):
    r = d.cmd(25)
    return dict(mode=r[5], rgb=tuple(r[6:9]), speed=r[9], brightness=r[10], sleep=r[11])


def get_4k_rgb(d):
    return d.cmd(21)[5]



def cmd_list(a):
    hid = import_hid()
    for d in hid.enumerate():
        if d['vendor_id'] in VIDS:
            m = d['usage_page'] == USAGE_PAGE and d['usage'] == USAGE
            print('%04x:%04x UP=%04x U=%02x if=%s %s %s' % (
                d['vendor_id'], d['product_id'], d['usage_page'], d['usage'],
                d['interface_number'], d.get('product_string'), '<== config iface' if m else ''))


def cmd_info(a):
    d = Dev(a.pid, rid_in=not a.no_rid)
    r = d.xfer(build(CMD['VERSION']))
    print('fw version: %x.%02x' % (r[5], r[6]))
    r = d.xfer(build(CMD['CIDMID']))
    print('cid,mid: %d,%d  uid %s' % (r[5], r[6], '.'.join('%02x' % b for b in r[11:15])))
    r = d.xfer(build(CMD['BATTERY']))
    print('battery: %d%% charging=%d mV=%d' % (r[5], r[6], (r[7] << 8) | r[8]))
    try:
        r = d.xfer(build(CMD['DONGLE_VERSION']))
        print('dongle version: %x.%02x' % (r[5], r[6]))
    except TimeoutError:
        print('dongle version: n/a')


def rate_block(d):
    return bytearray(d.eeprom(ADDR_RATE_BLOCK, 10))


def cmd_get_rate(a):
    b = rate_block(Dev(a.pid, rid_in=not a.no_rid))
    print('report rate: %s Hz (code %d, crc_ok=%s)' % (RATE_INV.get(b[0], '?'), b[0], b[1] == crc(b[0])))


def cmd_get_dpi(a):
    d = Dev(a.pid, rid_in=not a.no_rid)
    b = rate_block(d)
    print('stages=%d current=%d (0-based) crc_ok=%s' % (b[2], b[4], b[3] == crc(b[2]) and b[5] == crc(b[4])))
    n = 0
    for ad in ADDR_STAGE:
        raw = d.eeprom(ad, 8)
        for i in range(2):
            x, y, ex, c = raw[4 * i:4 * i + 4]
            print(' stage %d: X=%s Y=%s (raw %02x %02x %02x crc_ok=%s)' % (
                n, *('?' if v is None else v for v in dpi_decode(x, y, ex)), x, y, ex, c == crc(x, y, ex)))
            n += 1


def cmd_set_rate(a):
    if a.hz not in RATES_1K:
        sys.exit('rates: %s' % (RATES_1K,))
    set_rate(Dev(a.pid, rid_in=not a.no_rid, dry=not a.apply), a.hz)     # read-modify-write of the 10-byte block


def cmd_set_dpi(a):
    d = Dev(a.pid, rid_in=not a.no_rid, dry=not a.apply)
    set_dpi_stage(d, a.stage, a.x, a.y or a.x)
    if a.select is not None:
        set_dpi_current(d, a.select)


def _show(x):
    print(json.dumps(x, indent=1, default=str))


def cmd_get_all(a):
    d = Dev(a.pid, rid_in=not a.no_rid)
    out = dict(info=get_info(d), rate=get_rate(d)[0], dpi=get_dpi(d), func=get_func(d), lod_mm=get_lod(d)[0],
               sensor=get_sensor_mode(d), far=get_far(d), light=get_light(d), profile=get_profile(d))
    out['buttons'] = []
    for i, b in enumerate(get_buttons(d)):
        sh = get_shortcut(d, i) if b[0] == 5 else None
        out['buttons'].append('%s = %s' % (BUTTONS[i], describe_button(b, sh)))
    _show(out)


PARAMS = dict(debounce=lambda d, v: set_func(d, debounce=v), sleep=lambda d, v: set_func(d, sleep_s=v),
              motion_sync=lambda d, v: set_func(d, motion_sync=v), line_corr=lambda d, v: set_func(d, line_corr=v),
              ripple=lambda d, v: set_func(d, ripple=v), lod=set_lod, far=set_far, sensor_mode=set_sensor_mode,
              profile=lambda d, v: set_profile(d, v - 1))


def cmd_set_param(a):
    PARAMS[a.name](Dev(a.pid, rid_in=not a.no_rid, dry=not a.apply), a.value)


def cmd_set_light(a):
    set_light(Dev(a.pid, rid_in=not a.no_rid, dry=not a.apply), a.effect, LIGHT_BRIGHT[a.brightness], LIGHT_SPEED[a.speed])


def cmd_set_key(a):
    d = Dev(a.pid, rid_in=not a.no_rid, dry=not a.apply)
    cat = action_catalog()
    if not 1 <= a.button <= len(BUTTONS):
        sys.exit('button 1..%d' % len(BUTTONS))
    for items in cat.values():
        if a.action in items:
            try:
                return apply_action(d, a.button - 1, items[a.action])
            except ValueError as e:         # e.g. the Left/Right lock-out guard in set_button
                sys.exit(str(e))
    sys.exit('unknown action; see list-actions')


def cmd_list_actions(a):
    for c, items in action_catalog().items():
        print(c + ': ' + ', '.join(items))


def cmd_reset_keys(a):
    restore_default_buttons(Dev(a.pid, rid_in=not a.no_rid, dry=not a.apply))


def cmd_macros(a):
    d = Dev(a.pid, rid_in=not a.no_rid)
    for k in range(MACRO_SLOTS):
        m = macro_get(d, k)
        print('M%d: %s' % (k + 1, 'empty' if m is None else '%s (crc_ok=%s)' % (macro_to_text(m['actions']), m['crc_ok'])))


def cmd_macro_set(a):
    macro_set(Dev(a.pid, rid_in=not a.no_rid, dry=not a.apply), a.slot - 1, macro_from_text(a.text))


def cmd_macro_del(a):
    macro_delete(Dev(a.pid, rid_in=not a.no_rid, dry=not a.apply), a.slot - 1)


def cmd_export(a):
    cfg = export_config(Dev(a.pid, rid_in=not a.no_rid))
    with open(a.path, 'w', encoding='utf8') as f:
        json.dump(cfg, f, indent=1)
    print('wrote', a.path)


def cmd_import(a):
    with open(a.path, encoding='utf8') as f:
        cfg = json.load(f)
    print('problems:', validate_config(cfg) or 'none')
    import_config(Dev(a.pid, rid_in=not a.no_rid, dry=not a.apply), cfg)


def cmd_pair(a):
    if not a.apply:
        print('dry-run; pairing never runs without --apply')
    elif input('Type PAIR to start wireless pairing (the mouse may disconnect): ') != 'PAIR':
        sys.exit('aborted')
    pair_receiver(Dev(a.pid, rid_in=not a.no_rid, dry=not a.apply), a.cid, a.mid)


def cmd_factory_reset(a):
    if a.apply and input('Type RESET to wipe the mouse settings: ') != 'RESET':
        sys.exit('aborted')
    factory_reset(Dev(a.pid, rid_in=not a.no_rid, dry=not a.apply))


FW_URL = 'https://api-hub-cloud.atk.pro/firmware/%d/%d/%s'   # vendor JS (X9): vid/pid/firmwareMark


def _ver(s):
    """'3.15' / 'V3.15' / '3.15b' -> (3, 15); only trailing text after the dotted number is ignored. None if there is
    no leading number."""
    m = re.match(r'\s*[vV]?\s*(\d+(?:\.\d+)*)', str(s))
    return tuple(int(p) for p in m.group(1).split('.')) if m else None


MOUSE_FW_ID = (0x3554, 0xF58F, 'r1-se+')   # mouse entry (13652/62863/r1-se+): the query verified to return the version


def firmware_candidates(pid=None):
    """(vid, pid, mark) triples to query (at most two): the mouse ID first, then the connected interface's IDs as a
    fallback (for a dongle these may return the dongle's firmware, not the mouse's)."""
    hid = import_hid()
    out = [MOUSE_FW_ID]
    for d in find(hid, pid)[:1]:
        c = (d['vendor_id'], d['product_id'], 'r1-se+')
        if c != MOUSE_FW_ID:
            out.append(c)
    return out


def check_firmware(current, pid=None, timeout=10, candidates=None):
    """Manual, opt-in network GET (up to two requests). Returns dict(latest, newer, url, tried). Only vid/pid/mark are
    in the URL."""
    import urllib.request
    tried = []
    for vid, p, mark in candidates or firmware_candidates(pid):
        url = FW_URL % (vid, p, mark)
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'R1SE-Portable'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                j = json.loads(r.read().decode('utf8'))
        except Exception as e:
            tried.append((url, str(e)))
            continue
        v = (j.get('data') or {}).get('version') if isinstance(j, dict) else None
        tried.append((url, v))
        if v:
            lv, cv = _ver(v), _ver(current)
            comparable = lv is not None and cv is not None
            return dict(latest=str(v), newer=comparable and lv > cv, comparable=comparable, url=url, tried=tried)
    return dict(latest=None, newer=False, comparable=False, url=None, tried=tried)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--pid', type=lambda s: int(s, 0))
    p.add_argument('--no-rid', action='store_true', help='input reports carry no report id byte')
    p.add_argument('--apply', action='store_true', help='actually send write commands (default: dry-run)')
    s = p.add_subparsers(dest='c', required=True)
    for n, f in (('list', cmd_list), ('info', cmd_info), ('get-dpi', cmd_get_dpi), ('get-rate', cmd_get_rate),
                 ('get-all', cmd_get_all), ('list-actions', cmd_list_actions), ('reset-keys', cmd_reset_keys),
                 ('macros', cmd_macros), ('factory-reset', cmd_factory_reset)):
        s.add_parser(n).set_defaults(f=f)
    q = s.add_parser('set-rate')
    q.add_argument('hz', type=int)
    q.set_defaults(f=cmd_set_rate)
    q = s.add_parser('set-dpi')
    q.add_argument('stage', type=int)
    q.add_argument('x', type=int)
    q.add_argument('--y', type=int)
    q.add_argument('--select', type=int)
    q.set_defaults(f=cmd_set_dpi)
    q = s.add_parser('set-param', help='|'.join(PARAMS))
    q.add_argument('name', choices=list(PARAMS))
    q.add_argument('value', type=int)
    q.set_defaults(f=cmd_set_param)
    q = s.add_parser('set-light')
    q.add_argument('effect', choices=list(LIGHT_MODES))
    q.add_argument('brightness', choices=list(LIGHT_BRIGHT))
    q.add_argument('speed', choices=list(LIGHT_SPEED))
    q.set_defaults(f=cmd_set_light)
    q = s.add_parser('set-key')
    q.add_argument('button', type=int, help='1..6 = %s' % ', '.join(BUTTONS))
    q.add_argument('action', help='label from list-actions')
    q.set_defaults(f=cmd_set_key)
    q = s.add_parser('macro-set')
    q.add_argument('slot', type=int)
    q.add_argument('text', help="e.g. 'A+ A- @50 B+ B-'")
    q.set_defaults(f=cmd_macro_set)
    q = s.add_parser('macro-del')
    q.add_argument('slot', type=int)
    q.set_defaults(f=cmd_macro_del)
    for n, f in (('export', cmd_export), ('import', cmd_import)):
        q = s.add_parser(n)
        q.add_argument('path')
        q.set_defaults(f=f)
    q = s.add_parser('pair')
    q.add_argument('cid', type=int)
    q.add_argument('mid', type=int)
    q.set_defaults(f=cmd_pair)
    a = p.parse_args()
    a.f(a)


if __name__ == '__main__':
    main()
