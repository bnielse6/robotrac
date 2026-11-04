# Setup Guide

The tools this project needs, what is already installed on this PC, how to run everything, and what to do when something goes wrong.

## Table of contents

- [1. What is installed](#1-what-is-installed)
- [2. Setting up another machine](#2-setting-up-another-machine)
- [3. Commands you will use](#3-commands-you-will-use)
- [4. Where things get written](#4-where-things-get-written)
- [5. Troubleshooting](#5-troubleshooting)
- [6. Setting up the Raspberry Pi later](#6-setting-up-the-raspberry-pi-later)

---

## 1. What is installed

On this PC (Windows 11), installed during this project:

| Tool | Version | Installed how | Used for |
|---|---|---|---|
| Python | 3.12.10 | `winget install Python.Python.3.12 --scope user` | The Supervisor, simulator, dashboard and tests |
| PlatformIO | 6.2.0 | `python -m pip install --user platformio` | Building and flashing the ESP32 firmware |
| pyserial | 3.5 | Came with PlatformIO | The USB serial link (`serial_link.py`, `robot_main.py`) |
| ESP32 toolchain, ArduinoJson 7 | downloaded by PlatformIO on first build | Automatic, into `%USERPROFILE%\.platformio` (about 5.4 GB) | Compiling the firmware |

Python is at `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`. A terminal that was open before Python was installed may not find it. Open a new one.

`pio` is not on the PATH. Use `python -m platformio` instead.

Not installed: a C++ compiler for the PC (needed for the planned firmware unit tests), Wokwi (for the planned emulator), and any drivers for the ESP32's USB chip (see section 5).

## 2. Setting up another machine

1. Install **Python 3.9 or newer** from python.org. Tick "Add python.exe to PATH".
2. Open a terminal in the project folder. Check: `python --version`.
3. For the real serial link: `python -m pip install pyserial`.
4. For the firmware: `python -m pip install platformio`. Install the VS Code PlatformIO extension if you prefer an IDE.
5. Run the tests to confirm: in `supervisor`, `python -m unittest discover -s tests -t .` (expect 87 tests, OK).

The simulator, dashboard and tests need nothing beyond Python.

## 3. Commands you will use

| Task | Folder | Command |
|---|---|---|
| Open the visual simulator | `supervisor` | `python dashboard.py` (then it opens http://127.0.0.1:8765) |
| Run all tests | `supervisor` | `python -m unittest discover -s tests -t .` |
| Print a simulated run in the terminal | `supervisor` | `python run_sim.py happy` (also `plate-jam`, `refill`, `camera`, `estop`) |
| Run the real Supervisor with the real ESP32 | `supervisor` | `python robot_main.py --port COM5` |
| Build the firmware (simulated hardware) | `firmware/esp32` | `python -m platformio run` |
| Build the real-hardware firmware | `firmware/esp32` | `python -m platformio run -e esp32dev_real` |
| Flash the firmware | `firmware/esp32` | `python -m platformio run -t upload` |
| List serial ports | any | `python -m platformio device list` |

If `python` is not found, use the full path: `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`.

The dashboard has a Tests tab that runs the tests for you. Press Ctrl+C in the terminal to stop the dashboard.

## 4. Where things get written

| Path | What | Safe to delete? |
|---|---|---|
| `firmware/esp32/.pio/` | Firmware build output | Yes, it is rebuilt |
| `%USERPROFILE%\.platformio\` | The downloaded toolchain and libraries (about 5.4 GB on this PC) | Yes, it is downloaded again on the next build |
| `supervisor/**/__pycache__/` | Python's compiled files | Yes |
| Everything else in the project folder | Your work | No |

Nothing in the project writes logs or data files yet. The fault log is in memory only (see `next_steps.md`, A8).

## 5. Troubleshooting

| Problem | Cause and fix |
|---|---|
| `python` is not found, or opens the Microsoft Store | A terminal opened before the install, or the Store shortcut is in the way. Open a new terminal. If it persists, turn off the Python "app execution alias" in Windows Settings, Apps, Advanced app settings. |
| The dashboard shows "Cannot reach the dashboard server" | `dashboard.py` stopped. Start it again. |
| The dashboard opens but looks old or has no subsystem panels | An old copy of `dashboard.py` is still running on port 8765. Stop it (Task Manager, any `python.exe` running `dashboard.py`) and start it again. |
| `Address already in use` when starting the dashboard | The same cause. Or run on another port: `python dashboard.py --port 8800`. |
| `pio` is not recognized | Use `python -m platformio` instead. |
| The first firmware build is very slow | It is downloading the toolchain. This happens once. |
| `could not open port 'COM5'` | Wrong port, or another program (a serial monitor, an old `robot_main.py`) has it open. List ports with `python -m platformio device list`. |
| The board is not listed as a port | Cable is power-only, or the USB driver is missing. Many ESP32 boards use a CP210x or CH340 chip and need its driver. Try another cable first. |
| Upload fails with "Failed to connect" | Hold the BOOT button on the board while the upload starts. |
| Garbage or "bad line" errors from the link | Something other than protocol lines is being printed on the serial port, or the baud rate is not 115200 on both sides. The firmware must never `Serial.print` text. |
| The board resets every time `robot_main.py` starts | Normal. Opening the port resets most ESP32 boards, and the board announces `READY`. |
| A test fails after a change | Run the failing test alone: `python -m unittest tests.test_supervisor.Retries -v`. The test name says which rule broke. |

## 6. Setting up the Raspberry Pi later

Not done yet. Outline, to be confirmed when the Pi arrives:

1. Install Raspberry Pi OS (64-bit) on an SSD if possible, not an SD card.
2. `sudo apt install python3 python3-pip`, then copy the `supervisor` folder across.
3. `pip install pyserial`, and any camera libraries the vision code needs.
4. Find the ESP32 port: `ls /dev/ttyUSB*` or `/dev/ttyACM*`. Add the user to the `dialout` group to open it.
5. Run `python3 robot_main.py --port /dev/ttyUSB0`.
6. Later: start it automatically at boot (a systemd service), give the Pi a fixed Wi-Fi address for the operator screen, and add cooling and a stable power supply.
