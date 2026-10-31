# Reverse Engineering Notes: VXE / ATK Hub & R1 SE+

This directory contains research, static analysis artifacts, and methodology notes used to reverse-engineer the proprietary COMPX HID configuration protocol for the **VXE R1 SE+** gaming mouse.

---

## Source of Truth

The protocol definition was derived from static reverse-engineering of the official vendor software (ATK Hub / VXE Web & Electron application) and verified against live physical hardware (VXE R1 SE+ via 2.4 GHz wireless dongle `373B:1085`, firmware version `3.15`).

For complete protocol details, packet framing, and EEPROM address mapping, refer to:
👉 **[`../R1SE_Portable/docs/PROTOCOL.md`](../R1SE_Portable/docs/PROTOCOL.md)**

---

## Why Raw Vendor Dumps are Excluded

The local workspace originally contained:
- `atk_hub_extracted/`: Unpacked Electron ASAR bundles, NSIS installer archives (`app-64.7z`), and vendor executables (`ATK HUB.exe`) totaling over 700 MB.
- `rea_repo/`: Cloned reference repository of `morluto/rea`.

These directories are **excluded from Git tracking via `.gitignore`** for the following reasons:
1. **GitHub Size Limits**: GitHub enforces a strict 100 MB per-file limit. The vendor installer archive (`140 MB`) and executable (`186 MB`) would trigger immediate push rejections.
2. **Copyright & Compliance**: Redistributing vendor binaries and proprietary closed-source code is legally problematic. The clean-room documentation in `PROTOCOL.md` and the independent Python implementation in `R1SE_Portable` provide all required functionality legally and cleanly.

---

## How to Reproduce the Static Analysis

If you wish to inspect the vendor bundles or verify the offsets yourself:

1. Obtain the official installer for ATK Hub from the vendor.
2. Extract the installer using 7-Zip:
   ```bash
   7z x "ATK HUB.exe" -o"atk_hub_extracted"
   ```
3. Extract the Electron ASAR bundle using `@electron/asar`:
   ```bash
   npx @electron/asar extract atk_hub_extracted/app/resources/main/app.asar atk_hub_extracted/main_asar
   ```
4. Examine the JavaScript bundles in `main_asar/static/`:
   - `filter-3fyXcGGg.js`: COMPX device filter tables, HID command structures, EEPROM read/write routines, and parameter encoders.
   - `base-hid-device-*.js`: WebHID transport handling, report packet framing, retry logic, and timeouts.

---

## Included Files

- `hub_screenshot.png`: Reference screenshot of the vendor application UI for verifying feature mappings and controls.
