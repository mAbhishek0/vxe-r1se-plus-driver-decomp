# VXE/ATK R1SE+ HID protocol ("COMPX" mouse family) - static RE of ATK HUB

Source of truth: `research/atk_hub_extracted/main_asar/static/filter-3fyXcGGg.js` (145 KB; NOT demoMode.store). All offsets below are
char offsets in that file unless prefixed `D:` (demoMode.store-bFnXHZoS.js) or `V:` (VelotaSkinPreviewTransition-B9ZyQ_WL.js).
Sections 1-5 are the static analysis (Verified = read directly from code, Unverified = inferred). Hardware results are in section 6, which supersedes them.
The mouse path is `Wt` (controller, 69699) -> `Ot` (transport, 66183) -> `R` (base-hid-device-DSGIfKq_.js, WebHID). The
`UP=0xFF02/0xAA`-framed code in D:~806000 is the bootloader/firmware upgrader, `D:XR/FI` (reportId 4/5, evision) is a different vendor family;
index.js `usagePage 65376/usage 97` (0xFF60/0x61, VIA) is keyboards. None apply to R1SE+.

## 1. Device identification / interface

| Item | Value | Evidence |
|---|---|---|
| Vendor IDs | 0x3554 (VXE/ATK old) and 0x373B (ATK new) | filter list 94653+ |
| Config interface | usagePage 0xFF02 (65282), usage 0x0002 (verified on hardware; earlier static reading said 0xFF04) | COMPX filter entry (e.g. 103907); section 6 |
| Output report | Report ID 8, payload 16 bytes (`sendReport(8, 16B)`, no padding) | Ot.transferForResult 66320; Ke.SIZE=16 (30444) |
| Input report | 16+ bytes; app sees data with byte0 = echoed command id (WebHID strips report id) | Ot.handleInputReport |
| Feature reports | not used by this path | promiseRun `feature` default false (base-hid-device) |
| HID descriptor | not available statically; whether hidapi's read() prefixes a report id (likely 8) is UNVERIFIED -> tool strips a leading 8 if followed by cmd; `--no-rid` disables |

PIDs (VID 0x3554 = 13652 unless noted):

| Product | VID:PID | cid,mid | sensor | evidence |
|---|---|---|---|---|
| R1 / R1SE / **R1SE+** (white/black) | 3554:F58F (62863) shared | R1 2,11/12; R1SE 2,29/30; **R1SE+ 2,31 (fwMark r1-se+), 2,32, 2,116** | PAW3395SE | 103907-104246; 985186 |
| R1SE+ Silent | 373B:12BF (4799) | 2,130 | PAW3395SE | 103120 |
| R1SE+ (newer HW) | 373B:1358 (4952) | 2,136 | CORE26K | 136837 |
| R1SE+ Silent (newer HW) | 373B:1359 (4953) | 2,137 | CORE26K | 137136 |
| R1 PRO/MAX (for ref.) | 3554:F58C (62860) | 2,7/8/27/28/34 | PAW3395 | 99620 |

* The app does NOT distinguish models by PID alone: PID F58F is R1/R1SE/R1SE+; it calls cmd 16 (cid,mid) after opening (`getMouseCidMid` 72000ish, `identifyByCidMid:true`).
* Dongle vs wired: the app lists *receivers* separately (flag `receiver:!0`): 3554:F503/F505/F50B/F58A/F58D(62861, 4K)/F58E(62862, 1K)/FB12 (138910-139614). **F58F is NOT in the receiver list** - it is the "mouse" entry, i.e. what enumerates as the mouse (wired, or when the dongle presents the paired mouse). Your claim "dongle = F58F" is UNVERIFIED/contradicted; the receiver PIDs for the R1 gen are most likely F58D/F58E. Same interface (FF02/02) and same protocol either way; connection type is read at runtime with cmd 1 (below).
* Connection type: cmd 1 (`ze`, 36061) with 4 random bytes in data; reply `deviceType` = reply[5+6]: 0 dongle1K, 1 dongle4K, 2 wired1K, 3 wired8K, 4 dongle2K, 5 dongle8K, 6 wired2K, 7 wired4K (filter-hsnHUoY9.js enum `se`, 4566). The 4 random bytes are named `encryptedData`; the reply's first 4 bytes may be a challenge response - UNVERIFIED, not used by tool. (cmd 1 is also firmware "DownLoadData" - avoid on a live device unless needed.)
* Valid polling rates by connection (D:3072918/3051254): 125/250/500/1000 always; wired8K/dongle8K add 2K/4K/8K; dongle4K adds 2K/4K; dongle2K adds 2K.

## 2. Framing (Ke, 30444; transport Ot 66183 + base class R)

16-byte frame (big-endian address), sent as output report id 8:

```
[0] cmd id      [1] status (0 in requests; device sets in reply - values not defined in the app)
[2] addr hi     [3] addr lo        (EEPROM address, uint16 BE)
[4] data len    (valid bytes; for GET_EEPROM it is the number of bytes to read, <=10)
[5..14] data (10 bytes)
[15] checksum = (85 - (8 + sum(bytes[0..14]))) & 0xFF      # the 8 is the report id
```
* Reply: input report whose byte0 equals the request cmd id; the app matches pending request purely on that byte (`pendingTransfers`, requestCode = frame[0]). Reply layout is the same 16-byte layout (fields at same offsets; data at [5..]).
* Timeouts/retries: Ot sets TIMEOUT_MS=3000; base class retries up to MAX_RETRIES=3 (re-sends the same frame); after that returns a fake 64-byte reply with byte[2]=0xFF (error marker). One transfer at a time (mutex).
* Unsolicited reports: cmd 10 (`ReportMouseStatus`, 35665) with byte[5] bit flags: 1=DPI changed, 2=report rate, 4=profile, 8=dpi LED, 16=logo LED, 32=lamp, 64=battery. App then re-reads the EEPROM blocks. cmd 91/90 = upgrade status. Report id 0 inputs go to a no-op handler.
* EEPROM fields: values come in (value, crc) pairs with crc = (85 - value) & 0xFF (some blocks: crc of sum). App validates crc on read for newer fields (`isEepromCrcValid`, 87914) and ignores mismatching ones.

### Command ids (`Me`, 14333) - verified
1 DownLoadData(also connection-info), 3 GetWirelessMouseOnline, 4 GetBatteryLevel, 5/6 SetWirelessDonglePair/Result, 7 SetEEPROM, 8 GetEEPROM, 9 RestoreFactory, 10 ReportMouseStatus(notify), 13 EnterUSBUpgradeMode (**never send**), 14 GetCurrentConfig, 15 SetCurrentConfig, 16 GetMouseCIDMID, 18 GetMouseVersion, 19 DongleExitPair, 20/21 Set/Get4KRGBMode, 22/23 Set/GetFarDistanceMode, 24/25 Set/GetDongleLightMode, 29 GetDongleVersion, 90/91 upgrade notify.

## 3. Command table (R1SE+ = sensor PAW3395SE)

All "EEPROM addr" rows use cmd 8 (read, len = bytes) / cmd 7 (write, len = bytes, data at [5..]); write replies are acks (byte0 = 7). Writes apply immediately; **there is no separate "commit/save"** command in the code - EEPROM write = persisted on device.

| Feature | Operation (cmd / addr) | Encoding | Offsets | Confidence |
|---|---|---|---|---|
| Firmware version | cmd 18, len 0 | reply[5]=major(hex digits), reply[6]=minor; shown `%x.%02x` | _e 32756 | high |
| cid,mid / uid | cmd 16 | [5]=cid [6]=mid [11..14]=uid | Fe 32272 | high |
| Battery | cmd 4 | [5]=percent (cap 100) [6]=charge flag (1=charging) [7..8]=mV BE | Ve 31564; filter 70900 | high (layout) / med (units) |
| Dongle version | cmd 29, len 0, addr 0 | like fw version | He 35363 | high |
| Report rate | EEPROM addr 0 (block, 10 B): [0]=rate [1]=crc [2]=stageCount [3]=crc [4]=curStage [5]=crc [6]=bhop/10 [7]=crc [8]=btnOpMode [9]=crc | rate code: 1=1000, 2=500, 4=250, 8=125, 16=2000, 32=4000, 64=8000 (crc=85-code). Write = whole block (app rewrites rate+stageCount+curStage together; bytes 6-9 left zero(!) unless provided -> tool does read-modify-write) | je 36921; ReportRate enum 20157; setter 38xxx | high (read), med (write semantics) |
| DPI stage count / current stage | same block: [2] count (<=8), [4] current **0-based** index | crc 85-v | je; UI D:3045067 (index i from list, 0-based) | high / med |
| DPI stage values | EEPROM addr 12,20,28,36, 8 B each = 2 stages x 4 B (stage n at 12+4n): [xHex, yHex, dpiEx, crc=(85-(x+y+ex))&255] | PAW3395SE: hex -> DPI via 200-entry table (hex 1..235 = 50..10000 step 50; entries flagged `double` represent 2x). dpiEx bit1 (0x02) = X uses doubled value, bit5 (0x20) = Y uses doubled. Max 18000. Table saved: `dpi_table_3395se.json`. Newer CORE26K / 3950 sensors use different codecs (functions `ue` 1547 / `de`) - needed for 373B:1358/1359 | Je 40341; $e; oe 945; ne 1195; le table ~2000-14000; ue/de 1547 | high (decode/encode logic), med (that the R1SE+ firmware matches `sensor:PAW3395SE`) |
| DPI stage colour | addr 44,52,60,68, 8 B each = 2 x [r,g,b,crc(85-(r+g+b))] | | et 41900 | high |
| Select stage on device | write block 0 byte[4] (+crc) | RMW | je | med |
| DPI LED / mode | EEPROM addr 76, len 8: [mode(1 steady,2 breathing),crc][brightness (16/128/255),crc][speed (1/3/5),crc][enable(0/1),crc] | each crc=85-v | tt 42778 | high |
| Logo/decoration light | addr 160 (class mt 60755) | not decoded here | mt | unverified |
| Dongle light | cmd 24 set/25 get, len 10: [5]=mode [6..8]=rgb [9]=speed(0,5,9) [10]=brightness(0,5,9) [11]=sleep map{0:1,1:5,2:10} | | Ne 33376 | med (dongle only) |
| 4K RGB mode | cmd 20/21: [5]=mode (0 off,1 reportrate,2 battery,3 low battery) | | Xe 34869 | med |
| Lift-off distance | EEPROM addr 10, len 2: [v][crc]; v=1 -> 1 mm, 2 -> 2 mm (3 -> 0.7 mm only PAW3950) | UI V:409894 | Ze 38743 | high (addr/enc), med (units) |
| Far-distance (wireless long range) mode | cmd 22 set / 23 get; [5]=0/1, set uses len 10. Hidden for Silent (noFarDistance) | | Ge 32984 | high |
| Debounce | addr 169 (0xA9) in 10-B function block: [169]=debounce ms,[170]=crc | UI warns for <4; allowed list `ll`/`_l` imported, not read | at 44327 | med (unit ms) |
| Motion sync | addr 171: [v][crc] 0/1 | | at | high |
| Angle snap ("linear correction") | addr 175: [v][crc] 0/1 | | at | high |
| Ripple control | addr 177: [v][crc] 0/1 | | at | high |
| LED/idle sleep ("closeLedTime") | addr 173: [value/10][crc] (value in seconds presumably; UI default 30) | | at | med |
| Sensor sleep | addr 181: [enable][crc][time/10][crc][sensorModel][crc] (len 6) | UI setMouseSleepTime writes both | st 45662; 79xxx | med |
| Sensor angle (tuning) | addr 189: [angle][crc][enable][crc] (len 4) | | ct 59519 | high |
| Button remap | addr 96+4n (n=0..5: left,right,middle,side1,side2,bottom): [class,v1,v2,crc=(85-(c+v1+v2))&255]; read 8 B = 2 buttons | defaults left [1,1,0] right [1,2,0] middle [1,4,0] side1 [1,8,0] side2 [1,16,0] bottom [2,1,0]; classes 0 off,1 mouse(v1 bitmask 1 L,2 R,4 M,8 back,16 fwd),2 DPI(1 cycle?,2 +,3 -; labels unverified),3 roll L/R,4 fire,5 shortcut,6 macro,7 reportrate,9 profile,10 dpi lock,11 wheel | rt 46603; Ae 22398; setKey 72700 | high (layout), med (semantic of classes) |
| Macros | addr 768+384k (k<12): 31 B header, count @+31, 5-byte actions, written as one stream of 10 B frames; shortcut/keyboard combos at 256+32k | see section 6 | ot 48xxx | verified on hardware (section 6) |
| Profile (onboard slot) | cmd 14 get / 15 set, len 1, [5]=profile index | | Le 31949; getProfile 84700 | med (number of slots unknown) |
| Factory reset | cmd 9, len 0; the app then wipes macros (`_resetMacro`: 16 slots macro0..15 = 768..6911; the tool wipes only its 12 whitelisted slots 768..5375) | **destructive** | We 31867; resetDevice 72291 | high |
| Save to device | n/a - writes persist immediately | | | |
| Enter bootloader | cmd 13 | never | | |

## 4. Telemetry / network in the touched code paths

* UI actions call `dd.beginAction("mouse_dpi","set_dpi",{dpi_x,dpi_y})`, `mouse_performance/set_performance` etc. (D:~2108413, 3045000) - event tracker `Uploader` batches events and POSTs `.../track/upload` (D:928447; also `navigator.sendBeacon` on unload D:929056). Payload includes sessionId, userId, device vid/pid/cid/mid/deviceName/firmwareVersion (serializeEvent D:929300). `Jt` base URL not resolved here (axios instance).
* `V:` Velota cards also fire "埋点" (tracking) helpers (`ml`, `xl`, `Ul`) on debounce/sleep/LOD changes.
* Firmware/update: `https://api.vxe.com/v1/device/update/<id>/version|list` (D:4726761/4737936), Electron main: `https://api-hub-cloud.atk.pro/firmware/...`, `https://desktop.vxe.com/home|v3hub`, `https://api.keygen.sh/v1/accounts/` (licensing), `https://wallpaper.atkgear.com/list-v2.json`, assets `bpcdn.atkgear.com`.
* AI chat: `https://api-devdev.vxe.com/v1/ai/chat/completions` (needs login; sends deviceName/vid/pid).
* Local: `http://127.0.0.1:52339/device-init` (headset-related helper), `http://127.0.0.1:5577/exit` (service, main index.js).
* Raw HID commands themselves make no network calls. Not exhaustively hunted (service exe not inspected).

## 5. Open items / blockers
1. Real HID descriptor (report id of input reports, input report length) - needs a one-time read-only `hid.enumerate` + descriptor dump with hidapi on the actual device; tool has `--no-rid`.
2. Confirm PID roles (F58F is the mouse entry; receivers F58D/F58E) and that R1SE+ fw matches the PAW3395SE codec (check with `get-dpi`: crc_ok must be True and values sane).
3. Status byte values, error semantics, profile slot count, debounce/sleep option lists (imported symbols `ll/_l/dn` in V: not read).
4. (Resolved) `r1se_tool.py` is now verified on hardware for the items listed in section 6; offline tests use a fake HID device. CLI writes are dry-run unless `--apply`.

## 6. Hardware verification update (373B:1085 dongle, R1 SE+, cid,mid 2,32, fw 3.15; iface FF02/02, report id 8)

Verified on hardware = write -> readback -> restore -> compare (full-region diff vs start was identical):
rate block; DPI stage X/Y independently (stage 4 1600x1200); current stage; function block @169 (debounce ms @169, motion sync @171,
sleep s/10 @173, line correction @175, ripple @177, each [v,85-v]; vendor writes the whole 10 B block); LOD @10; sensor mode @185
(0 basic, 1 competitive; block @181 = [sleepEn,crc,sleep/10,crc,model,crc]); far distance cmd 22 (set, len 10, [5]=0/1) / 23 (get, [5]);
DPI light @76 ([mode 1 steady/2 breathing][brightness 16/128/255][speed 1/3/5][enable] each + crc; "Close" = enable 0);
profile cmd 14 (get, [5]) / cmd 15 (set, len 1, [5]) - 0-based 0..3, switched 0->1->0 OK; button remap @96+4n (n: 0 L,1 R,2 M,3 back,4 forward,5 DPI)
[class,v1,v2,85-sum]; class 1 mouse (v1 bit: 1 L,2 R,4 M,8 back,16 fwd, 0 = disable), 2 DPI (1 cycle,2 +,3 -), 3 roll L/R (1/2), 9 config
(v1 161..164 switch, 255 cycle), 11 wheel up/down (1/2), 6 macro (v1 slot, v2 mode: 254 stop, 253 repeat-until-press, 255 repeat-until-any, N count),
5 shortcut. Shortcut data @256+32n: [count][3-byte actions: byte0 = type(0 modifier,1 key,2 media,3 power,4 mouse) | 0x80 down / 0x40 up, v1, v2]..[crc = 85-sum(count+actions)];
multimedia = type 2, v1 = HID consumer usage low byte, v2 = page code (table in r1se_tool.MULTIMEDIA); keyboard = type 1 (HID usage), modifiers = type 0 (bitmask).
Key+modifier combos ([mods down, key down, mods up, key up]) verified on hardware by the user: Ctrl+A selected all text, Ctrl+Shift+Esc opened Task Manager.
Macros (slot k @768+384k): 31 B header [8, 2x8, 255x22], count @+31, 5 B actions from +32 [byte0 as above, v1, v2, delay u16 BE], crc 85-sum(count+actions),
vendor writes zero-padded 10 B frames. Names are not stored on the device. Hardware: first blank-slot write (slot 12) + readback + assign OK;
afterwards writes to slot 11 (0x1200) and rewrites of slot 12 were silently dropped by the device (ack but no change) - most likely caused by the old per-frame read-back/resend writer; the stream writer below does not show it.
Macro writes MUST be one uninterrupted stream of 10-byte frames starting at the slot base (header first, no reads or resends between frames); the ack is a plain echo with status 0 even when a write is ignored. A resent frame is appended and corrupts the slot. Verify once at the end, redo the whole stream on mismatch. Hardware-verified: set, rewrite and delete (header + count 0) on slots 11 and 12. Corrupt slot 12 from the earlier per-frame retry bug was cleared this way. Macro assigned to the Advance button with mode v2=1 ran the macro exactly once when pressed (verified by user). Mode 253 (repeat until next press of the button) and mode 255 (repeat until any MOUSE button; a keyboard key does not stop it) verified by user; delay unit is ms (500+500 gave one key per second).
Sensor mode "Competitive Max" (value 2) = needs corded firmware -> not offered. Unverified: fire key (class 4) units; finer light speed steps (only 1/3/5 known); dongle light (cmd 24/25) and 4K RGB (cmd 20/21) value mapping (read only);
pair (cmd 5/6) and factory reset (cmd 9) implemented, never run. cmds 1, 13, 90, 91 (download/USB upgrade/upgrade notify): hard-blocked in Dev.xfer (PermissionError before anything is sent); firmware upgrade not implemented.
Status/ack: write replies echo cmd 7 with addr/len; reads of cmd 14/15 etc. work through the same 16 B frames. Mouse sleeps: first commands time out until moved.
Tool transport rules: pending input is drained before each request; cmd 7/8 replies must echo the request's addr/len bytes [2..4] (a stale reply is skipped);
read-modify-write helpers refuse to write when a field they would write back unchanged has a bad CRC. Left/Right can never be set to class 0 or class 1 with v1 = 0,
and at least one of Left/Right always stays a mouse click (class 1 with v1 & 3 != 0; checked against the other button read from the device, and on the imported block 96).
Button entries written/imported are limited to the offered classes: 1 (v1 0/1/2/4/8/16), 2 (1-3), 3 (1/2), 5 (0,0), 6 (slot < 12, v2 1..255), 9 (161-164/255), 11 (1/2).
Rate block bytes 6-9 read 00 55 00 55 on the test mouse (bhop 0, button operation mode 0, valid CRCs). Import accepts only zeros or valid pairs there,
then requires zeros or the device's current bytes and always writes the device's bytes back (never changes them).
Macros are capped at 69 actions (32 + 5*69 + 1 = 378 B, padded to 380 <= 384 B slot) so the stream never reaches the next slot; delays 0..65535 ms.
