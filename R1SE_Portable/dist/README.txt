R1SE_Portable - VXE R1 SE+ settings tool (portable, no install, no telemetry). The only network access is the manual firmware version check. Files written: r1se_config.json (theme choice) and r1se_errors.log (errors/crashes only) next to the exe, and a config export at a path you choose.
Run R1SE_Portable.exe. The mouse sleeps: if you see a timeout error, move the mouse and press "Refresh all"/retry. After an error the device is reopened on the next action, so unplug/replug or cable <-> dongle needs no restart.
Tabs: Key Change Settings | Macro Settings | DPI Settings | Performance | Parameter | Config | Other.
CLI/library: python r1se_tool.py get-all | set-param ... | set-key ... | export/import ... (writes are dry-run unless --apply; pair and factory-reset also need a typed confirmation).

VERIFIED on hardware (R1 SE+ via dongle 373B:1085, fw 3.15; write -> readback -> restore, region diff identical):
 polling rate 125..1000; DPI stages (X and Y independent) and active stage; Performance mode Daily/Game Competitive;
 movement sync, straight-line correction, ripple correction, key debounce, sleep time, lift-off 1/2 mm, Ultra Long Range (cmd 22/23);
 DPI light effect/brightness/speed (Slow/Medium/Fast); onboard config 1-4 read/switch (cmd 14/15);
 button remap (mouse/DPI/config/wheel classes; multimedia: stored data verified) and keyboard shortcuts with modifiers (Ctrl+A selects all, Ctrl+Shift+Esc opens Task Manager);
 Restore Default buttons (changed Back and Advance, restore returned all six to default);
 macros: save, rewrite, delete (slots 11 and 12), assign to a button, Run once, Repeat until next press, Repeat until any mouse button
 (a keyboard key does not stop it), delay unit = ms; config export/import round trip (changed DPI stage 2, polling rate, Back button and
 lift-off, import restored everything).
IMPLEMENTED, NOT TESTED: Pair receiver (cmd 5/6), Factory reset (cmd 9).
UNVERIFIED (not offered / read-only): fire key (Special), dongle light and 4K RGB modes (read-only), finer light speed steps
 (only Slow/Medium/Fast codes known), Competitive Max mode.
NOT IMPLEMENTED on purpose: firmware upgrade, USB upgrade mode; commands 1, 13, 90, 91 are refused by the library before anything is sent.

Safety: Left/Right can never be disabled, and at least one of Left/Right always stays a mouse click (GUI, CLI and library refuse it,
 and imports containing it are rejected). Import accepts only known addresses with valid checksums and the same values the settings
 controls allow (rates 125..1000, known DPI codes, debounce/sleep lists, LOD 1/2, light values, sensor mode 0/1, only the button actions
 the tool offers, macro slot 1..12, macros up to 69 steps with valid checksums). Import never changes rate-block bytes 6-9 (button
 operation mode): the file must hold zeros or the mouse's current bytes. When a setting is changed by read-modify-write, the write is
 refused if a field that would be written back unchanged has a bad checksum. Exports from older builds that contain DPI colour blocks
 still import; those blocks are ignored. Factory reset wipes macro slots 1..12 (the vendor app also clears 4 more slots this tool does
 not use). Closing the window while a write is pending asks first and closes only after the pending operations have finished.

Firmware check: Other tab, manual button, check only (never flashes). Sends up to two GETs to api-hub-cloud.atk.pro/firmware/<vid>/<pid>/r1-se+
 (the R1 SE+ mouse IDs 3554:F58F first - the query that returns the mouse version - then the connected device's IDs as a fallback; for a
 dongle those may return the dongle firmware, which the result then says). Versions are compared numerically (e.g. 3.15 > 3.9); if a
 version cannot be parsed the result says so instead of guessing.

Theme: top-right selector System/Light/Dark. System follows the Windows app mode instantly (registry change notification). The choice is saved in r1se_config.json next to the exe.

Errors: only on errors or crashes, r1se_errors.log next to the exe (timestamp + message/traceback, rotates at 1 MB). Nothing is logged during normal use.

Tooltips: hover any control or label for ~0.5 s for a short explanation of what it does and whether it applies immediately or needs Apply.
