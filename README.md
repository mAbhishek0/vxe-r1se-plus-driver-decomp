# R1SE_Portable: VXE R1 SE+ Configuration Tool & Protocol

[![Platform](https://img.shields.io/badge/platform-Windows-blue.svg)](https://github.com)
[![Python](https://img.shields.io/badge/python-3.8+-brightgreen.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Hardware Verified](https://img.shields.io/badge/Hardware-Verified-success.svg)](#hardware-verification-status)

A lightweight, portable, telemetry-free configuration tool and reverse-engineered HID protocol documentation for the **VXE / ATK R1 SE+** gaming mouse (PAW3395SE sensor).

Unlike the bloated official vendor software (ATK Hub), this tool requires **no installation**, **no background services**, and **no network tracking**. It runs as a standalone native GUI or a scriptable CLI.

---

## Table of Contents

- [Why R1SE_Portable?](#why-r1se_portable)
- [Hardware Verification Status](#hardware-verification-status)
- [Features](#features)
- [Safety & Guardrails](#safety--guardrails)
- [Installation & Quick Start](#installation--quick-start)
  - [Option 1: Standalone Executable (Recommended)](#option-1-standalone-executable-recommended)
  - [Option 2: Running from Python Source](#option-2-running-from-python-source)
- [CLI Reference](#cli-reference)
- [Building from Source](#building-from-source)
- [Protocol Documentation & Research](#protocol-documentation--research)
- [Repository Structure](#repository-structure)
- [Disclaimer & License](#disclaimer--license)

---

## Why R1SE_Portable?

| Feature | Official ATK Hub | R1SE_Portable |
|---|---|---|
| **Installation** | Requires installer, Electron framework | Completely portable (single `.exe` or Python script) |
| **Telemetry / Tracking** | Batches user events, clicks, sends metrics | **Zero telemetry** (only opt-in manual firmware version check) |
| **Background Services** | Installs persistent daemon processes | **None**; leaves no background processes running |
| **CLI / Automation** | Not supported | Full CLI support with JSON export/import and dry-run safety |
| **System Theme** | Fixed styling | Follows Windows Light/Dark mode dynamically (event-driven) |

---

## Hardware Verification Status

The configuration commands and EEPROM layouts were derived via static reverse-engineering and **physically verified on real hardware**:

- **Target Device**: VXE R1 SE+ via 2.4 GHz wireless dongle (`VID:PID = 373B:1085`, USB mouse descriptor `3554:F58F`)
- **Firmware Tested**: `3.15`
- **Sensor**: PixArt PAW3395SE (uses custom non-linear 200-entry DPI index table)

### Verified Operations:
- [x] Polling rate configuration (125 Hz, 250 Hz, 500 Hz, 1000 Hz)
- [x] Independent X and Y DPI stages (1 to 8 stages) and active stage switching
- [x] DPI stage indicator RGB LED colors
- [x] Performance modes: Daily mode vs Game Competitive mode
- [x] Sensor parameters: Motion Sync, Straight-Line Correction (Angle Snapping), Ripple Correction
- [x] Key debounce timing (0–20 ms) and idle sleep timeout (seconds)
- [x] Lift-off distance (LOD: 1 mm / 2 mm)
- [x] Wireless Far-Distance (Ultra Long Range) mode (`cmd 22/23`)
- [x] DPI LED light modes (Steady / Breathing), brightness, and animation speed
- [x] Onboard config profile switching (Profiles 1–4)
- [x] Full button remapping (Mouse buttons, DPI cycle, wheel clicks, media keys, keyboard keys with modifiers like `Ctrl+Shift+Esc`)
- [x] Restore default button assignments
- [x] Hardware macro creation, update, deletion (slots 1–12), and button binding (Run once, Repeat until next press, Repeat until any mouse click)
- [x] Configuration backup export and restoration round-trip verification

### Safety Notice:
- **Refused by Design**: Firmware flash and USB upgrade mode commands (`1`, `13`, `90`, `91`) are explicitly blocked by the library to prevent device bricking.
- **Pairing & Factory Reset**: Implemented but requires explicit user confirmation.

---

## Features

- **Graphical User Interface (GUI)**:
  - Clean native Tkinter interface with tabs: *Key Change Settings*, *Macro Settings*, *DPI Settings*, *Performance*, *Parameter*, *Config*, *Other*.
  - Instant hotplug and sleep recovery: if the mouse enters deep sleep, waking it automatically recovers communication without restarting the app.
  - Automatic light/dark theme synchronization responding to Windows OS personalization settings via `RegNotifyChangeKeyValue`.
  - Tooltips on every setting explaining the behavior and whether it persists immediately.
- **Command-Line Interface (CLI)**:
  - Inspect, query, and modify mouse parameters from scripts or terminal.
  - Safe dry-run mode enabled by default; requires `--apply` to commit changes to EEPROM.
- **Config Backup & Migration**:
  - Export full mouse configuration to JSON and restore it onto any compatible mouse.

---

## Safety & Guardrails

1. **Lockout Protection**: Left and Right click buttons can never be disabled simultaneously. At least one button must always remain a functional primary mouse click.
2. **EEPROM Checksum & CRC Verification**: Every packet is protected by a frame checksum (`85 - (8 + sum(bytes))`). EEPROM blocks use per-byte CRC validation (`85 - value`). Writes are aborted if existing fields fail checksum checks.
3. **Atomic Read-Modify-Write**: Settings updates preserve untouched bits and bytes in the EEPROM block.
4. **Bricking Prevention**: Destructive bootloader and firmware upgrade commands are filtered out before reaching the USB transport layer.

---

## Installation & Quick Start

### Option 1: Standalone Executable (Recommended)

1. Download the latest `R1SE_Portable.exe` from the [Releases](https://github.com) page.
2. Plug in your mouse or 2.4 GHz wireless dongle.
3. Run `R1SE_Portable.exe` (no installation required).

### Option 2: Running from Python Source

#### Prerequisites
- Windows 10/11
- Python 3.8 or newer
- `hidapi`

#### Setup
```bash
# Clone the repository
git clone https://github.com/your-username/ReEng.git
cd ReEng

# Install dependencies
pip install -r requirements.txt

# Launch the GUI
python R1SE_Portable/src/r1se_gui.py

# Or run the CLI tool
python R1SE_Portable/src/r1se_tool.py --help
```

---

## CLI Reference

The CLI tool (`r1se_tool.py`) enables command-line administration. **By default, writes run in dry-run mode.** Pass `--apply` to commit changes to hardware.

```bash
# List connected compatible devices
python R1SE_Portable/src/r1se_tool.py list

# Print device info (firmware version, battery, CID/MID)
python R1SE_Portable/src/r1se_tool.py info

# Query current DPI configuration
python R1SE_Portable/src/r1se_tool.py get-dpi

# Query report rate (polling rate)
python R1SE_Portable/src/r1se_tool.py get-rate

# Set polling rate to 1000 Hz
python R1SE_Portable/src/r1se_tool.py set-rate 1000 --apply

# Set key debounce to 4 ms
python R1SE_Portable/src/r1se_tool.py set-param debounce 4 --apply

# Set Lift-Off Distance (LOD) to 1 mm
python R1SE_Portable/src/r1se_tool.py set-param lod 1 --apply

# Export complete mouse profile to JSON
python R1SE_Portable/src/r1se_tool.py export mouse_backup.json

# Restore configuration from backup
python R1SE_Portable/src/r1se_tool.py import mouse_backup.json --apply
```

---

## Building from Source

To compile the portable standalone executable:

```bash
# Install PyInstaller
pip install pyinstaller hidapi

# Run the build script
cd R1SE_Portable
build.bat
```

The compiled binary will be located at `R1SE_Portable/dist/R1SE_Portable.exe`.

---

## Protocol Documentation & Research

Comprehensive documentation of the COMPX 16-byte framing protocol, EEPROM memory addresses, command IDs, and sensor tables is available:

- 📄 **[Protocol Specification Document](R1SE_Portable/docs/PROTOCOL.md)**:
  - 16-byte frame structure and checksum formula
  - Complete EEPROM memory map (DPI, rates, buttons, macros, performance)
  - Sensor-specific encoding (PAW3395SE non-linear lookup table)
  - Command ID catalog and unsolicited status report formats
- 🔬 **[Research & Extraction Methodology](research/README.md)**:
  - Reverse engineering process and static analysis background
  - Notes on vendor bundle structure

---

## Repository Structure

```
ReEng/
├── .github/
│   └── workflows/
│       └── build.yml             # GitHub Actions automated PyInstaller build CI
├── R1SE_Portable/
│   ├── build.bat                 # PyInstaller one-click build script
│   ├── dist/
│   │   └── README.txt            # Quick reference distributed with the binary
│   ├── docs/
│   │   └── PROTOCOL.md           # Complete reverse-engineered HID protocol spec
│   ├── src/
│   │   ├── dpi_table_3395se.json # PAW3395SE sensor DPI lookup table
│   │   ├── r1se_gui.py           # Portable Tkinter graphical user interface
│   │   └── r1se_tool.py          # Core library & CLI interface
│   └── requirements.txt          # Python dependencies
├── research/
│   ├── README.md                 # Reverse engineering notes & reproduction steps
│   └── hub_screenshot.png        # Reference vendor application UI screenshot
├── .gitignore                    # Ignores large vendor dumps, binaries, and caches
├── LICENSE                       # MIT License
├── README.md                     # Main repository documentation
└── requirements.txt              # Project dependencies
```

---

## Disclaimer & License

This project is an independent reverse-engineering effort developed for interoperability, privacy, and educational purposes. It is not affiliated with, authorized, or endorsed by VXE, ATK, or PixArt.

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for details.
