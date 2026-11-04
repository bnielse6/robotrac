# ESP32 firmware

Runs the Locomotion, Plate, Screw and Fastening subsystems and talks to the Raspberry Pi over USB serial.

**Compiles (both environments, no warnings). Not yet run on a board.** The full explanation is in `../../diagrams/firmware_guide.md`.

## Build

Needs PlatformIO (VS Code extension, or `pip install platformio`). If `pio` is not found, use `python -m platformio` in its place.

    pio run                      simulated hardware (default, nothing needs wiring)
    pio run -t upload            flash it
    pio run -e esp32dev_real     real hardware (every function in src/hal_esp32.cpp is a TODO)

The first build downloads the toolchain (about 5.4 GB on disk, a few minutes). `.pio/` holds build output and can be deleted.

Do not open the serial monitor: the port carries only protocol lines.

## Try it

1. Flash the simulated build.
2. From `../../supervisor`, run `python robot_main.py --port COM5` (your port) and type `start`.

## Where things are

| Path | What |
|---|---|
| `src/main.cpp` | Loop, message dispatch, heartbeat watchdog, stack light flashing |
| `src/protocol.*` | JSON line format |
| `src/locomotion.*`, `plate.*`, `screw.*`, `fastening.*` | The four flowcharts (S1 to S5) |
| `src/hal.h`, `hal_sim.cpp`, `hal_esp32.cpp` | Hardware interface, simulated, real |
| `include/config.h` | Limits, tolerances, pin map |
