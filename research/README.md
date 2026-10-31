# Reverse Engineering Notes: VXE / ATK Hub & R1 SE+

This directory contains research, static analysis artifacts, and methodology notes used to reverse-engineer the proprietary COMPX HID configuration protocol for the **VXE R1 SE+** gaming mouse.

---

## Source of Truth

The protocol definition was mapped out by deconstructing the official vendor software (ATK Hub). Bundle exploration was conducted with [morluto/rea](https://github.com/morluto/rea), paired with Claude Sonnet 5.5 and Claude Opus 5.5 for navigating the minified JavaScript and reconstructing the HID framing logic. Every command and memory offset was then validated against live physical hardware (VXE R1 SE+ via 2.4 GHz wireless dongle `373B:1085`, firmware `3.15`).

For complete protocol details, packet framing, and EEPROM address mapping, refer to:
👉 **[`../R1SE_Portable/docs/PROTOCOL.md`](../R1SE_Portable/docs/PROTOCOL.md)**

---

## Analysed Version

- **Vendor application**: ATK HUB `3.2.30` (Electron app)
- **Installer**: `atk-hub-3.2.30.exe`, SHA-256 `4a7e9068511d8b44a7c68b525d03c9da33555e97937b02977f3a2dba115c163f`
- **Main bundle**: `app/resources/main/app.asar`, SHA-256 `1e4b689f19504fff4bac1aba567b475198f79fb9f21d0eabcc2a5e85582bb56b`
- **Device firmware tested**: `3.15` (VXE R1 SE+ via 2.4 GHz wireless dongle `373B:1085`)

---

## Why Raw Vendor Dumps are Excluded

The local workspace originally contained:
- `atk_hub_extracted/`: Unpacked Electron ASAR bundles, NSIS installer archives (`app-64.7z`), and vendor executables (`ATK HUB.exe`) totaling over 700 MB.
- `rea_repo/`: Cloned workspace of morluto/rea used for code analysis.

These directories are **excluded from Git tracking via `.gitignore`** for the following reasons:
1. **GitHub Size Limits**: GitHub enforces a strict 100 MB per-file limit. The vendor installer archive (`140 MB`) and executable (`186 MB`) would trigger immediate push rejections.
2. **Copyright & Compliance**: Redistributing vendor binaries and proprietary closed-source code is legally problematic. The clean-room documentation in `PROTOCOL.md` and the independent Python implementation in `R1SE_Portable` provide all required functionality legally and cleanly.

---

## How to Reproduce the Static Analysis

If you wish to inspect the vendor bundles or verify the offsets yourself:

1. Obtain the official installer for ATK Hub 3.2.30 from the vendor and verify its SHA-256 against the value above.
2. Extract the installer using 7-Zip:
   ```bash
   7z x "atk-hub-3.2.30.exe" -o"atk_hub_extracted"
   ```
3. Extract the Electron ASAR bundle using `@electron/asar`:
   ```bash
   npx @electron/asar extract atk_hub_extracted/app/resources/main/app.asar atk_hub_extracted/main_asar
   ```
4. Examine the JavaScript bundles in `main_asar/static/`:
   - `filter-3fyXcGGg.js`: COMPX device filter tables, HID command structures, EEPROM read/write routines, and parameter encoders.
   - `base-hid-device-*.js`: WebHID transport handling, report packet framing, retry logic, and timeouts.

   > **Note:** Bundle filenames contain build hashes and will differ in other ATK HUB versions. If they don't match, search `main_asar/static/` for `COMPX` to locate the filter tables.

---

## Included Files

- `hub_screenshot.png`: Reference screenshot of the vendor application UI for verifying feature mappings and controls.
