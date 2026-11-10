# Roofing Robot: Controllers and Electrical Setup (Recommendation)

Written 2026-11-03. This is a **recommendation**, not a decision. It builds on `hardware_architecture.md` (Pi 5 + ESP32 + hardware E-stop, already decided) and fills in the parts that file leaves open: power, drivers, noise, the stack light and the operator controls. Several parts depend on hardware you have not chosen yet, listed in section 8.

## Table of contents

- [1. Summary](#1-summary)
- [2. Controllers](#2-controllers)
- [3. Power and E-stop](#3-power-and-e-stop)
- [4. Drivers and actuators](#4-drivers-and-actuators)
- [5. Noise and grounding](#5-noise-and-grounding)
- [6. Camera and operator controls](#6-camera-and-operator-controls)
- [7. Bring-up order](#7-bring-up-order)
- [8. Decisions needed from you](#8-decisions-needed-from-you)

---

## 1. Summary

Keep the Pi 5 plus one ESP32-S3 split you already have, isolate the USB link, and put a hardware E-stop between the battery and everything that moves.

- **Controllers:** Raspberry Pi 5 (8 GB) for the Supervisor, camera and operator page. One ESP32-S3 for Locomotion, Plate, Screw and Fastening.
- **Link:** USB serial through a USB isolator, to keep drill and motor noise off the Pi.
- **Power:** a 24 V battery feeds two branches. A motor rail goes through the E-stop contactor. A separate logic rail powers the Pi and ESP32, so alerts, logs and the stack light still work after an E-stop.
- **Operator:** a tablet on the Pi's Wi-Fi, plus physical START and RESOLVED buttons on the robot as a backup.

```
                       +--------------------------------------------+
                       |  Raspberry Pi 5 (8 GB)                     |
                       |  Supervisor, camera, operator web page     |
                       +----------------+---------------------------+
                                        | USB serial (through USB isolator)
                       +----------------v---------------------------+
   buttons, sensors -->|  ESP32-S3                                  |--> stack light (3 outputs)
   E-stop status ----->|  Locomotion, Plate, Screw, Fastening       |
                       +---+------------+------------+--------------+
                           |            |            |
                      motor drivers  plate/screw   drill driver
                           |         drivers          |
   Battery 24 V --> fuse --+--> E-STOP CONTACTOR ---> motor / drill / actuator rail
        |
        +--> separate fuse --> DC-DC 5 V / 5 A (Pi) and 5 V / 3.3 V (ESP32, sensors)
```

## 2. Controllers

One Pi and one ESP32-S3 is enough. Split the ESP32 only if testing shows noise or timing problems.

- **Raspberry Pi 5 (8 GB)** runs the Supervisor, the camera and the operator page. Give it an active cooler in a shaded enclosure, and boot it from an SSD.
- **ESP32-S3 instead of the plain ESP32.** It has more usable pins and native USB. You need about 30 I/O:

| Group | Approx. pins |
|---|---|
| Encoders (2 wheels, A and B) | 4 |
| Drive motor PWM and direction (2 motors) | 4 to 6 |
| Crest sensors and front sensor | 3 to 5 |
| Plate feed, push, release | 3 |
| Plate supply sensor, tripwire | 2 |
| Screw load, screw supply sensor | 2 |
| Drill PWM and direction, retract switch | 3 |
| Torque input (ADC or HX711) | 1 to 2 |
| Stack light (red, amber, green) | 3 |
| E-stop status, physical START and RESOLVED buttons | 3 |

  If you run short, add an I2C pin expander (MCP23017) rather than a second board.
- **USB isolator between the Pi and the ESP32** (ADuM3160 type, about $15). Drill and motor noise is the most likely cause of random serial dropouts. Isolating the link removes the shared-ground path. This matters more than adding a second microcontroller.
- **If you do split:** one ESP32 for Locomotion, one for Plate, Screw and Fastening. The Supervisor and the message schema already support it, because subsystems only talk to the Supervisor.
- **Why not a PLC or a Jetson:** a PLC is overkill and awkward for the camera work. A Jetson is only worth it if measured camera latency shows the Pi 5 is too slow (see `hardware_architecture.md`).

## 3. Power and E-stop

Split the power into a motor side that the E-stop can cut, and a logic side that stays on.

```
Battery (24 V) -> main fuse -> E-stop contactor -> motor, drill and actuator rail (24 V)
               \-> separate fuse -> DC-DC 5 V / 5 A (Pi)
                                  -> DC-DC 5 V / 3.3 V (ESP32, sensors)
```

- **The E-stop is hardware, as already decided.** A normally-closed mushroom button sits in the coil circuit of a contactor or safety relay. It cuts the motor, drill and actuator rail.
- **A second contact on the button goes to an ESP32 input**, so the Supervisor can log `ESTOP`.
- **The Pi and ESP32 stay powered after an E-stop.** The alert, the fault log and the stack light (red) keep working.
- **Motor driver enable pins go through the E-stop circuit too.** A stuck ESP32 pin then cannot keep the wheels powered.
- **The Pi needs a proper 5 V / 5 A supply.** A weak buck converter is the usual cause of Pi 5 brownouts.
- **A power loss mid-run** needs a decision (see question 7 in `next_steps.md`). A small UPS or supercapacitor on the logic rail lets the Pi write its fault log and shut down cleanly.
- **If this robot is ever used near people**, replace the plain contactor with a proper safety relay (Pilz PNOZ type). For the capstone prototype a contactor is acceptable, but state that in the report.

## 4. Drivers and actuators

| Part | Recommendation | Note |
|---|---|---|
| Drive motors | Brushed DC gear motors with quadrature encoders | Undecided, see section 8 |
| Drive motor drivers | H-bridge drivers (BTS7960 or Cytron MD-class) | Enable pins gated by the E-stop |
| Plate feed, push, release | Solenoids or small linear actuators on MOSFET or relay boards | Undecided, depends on the mechanism |
| Screw load | Same as the plate outputs | Flyback diode on every coil |
| Drill | A commercial drill/driver, not a custom build | Biggest source of current and noise |
| Torque sensing | Motor current (INA226 or ACS series) as a proxy, or an inline torque sensor with an HX711 amplifier | The 10 s torque limit in the guide needs a real torque reading |
| Retract switch | A plain limit switch to an input | Fastening never replies until it closes |
| Stack light | 24 V LED stack light on three opto-isolated relay or MOSFET channels | Pins `PIN_LIGHT_RED`, `PIN_LIGHT_AMBER`, `PIN_LIGHT_GREEN` in `config.h` |
| Sensors | Depends on the type. 5 V or 24 V industrial sensors need level shifting to the ESP32's 3.3 V | Undecided |

## 5. Noise and grounding

- **One star ground point.** Motor and drill grounds return there, not through the logic ground.
- **Isolate the USB link** (section 2).
- **Flyback or TVS diodes** on every inductive load: solenoids, motors, the contactor coil.
- **Shielded twisted pair for the encoders**, shield grounded at one end.
- **Ferrites and short leads** on the drill motor.
- **Keep the logic wiring away from the drill wiring**, and cross it at right angles when it must cross.

## 6. Camera and operator controls

- **Camera:** a Pi camera module (global shutter if possible) or a USB camera, with an LED ring light inside the enclosure. Measure the capture-to-answer latency early, because it sets the plate and screw timeouts.
- **Operator screen:** a tablet on a Wi-Fi hotspot hosted by the Pi.
- **Wi-Fi on a roof is a weak point.** If it drops, the operator cannot press RESOLVED. I recommend adding **physical START and RESOLVED buttons on the robot**, wired to the ESP32. They work even if the tablet drops, and the stack light tells the operator when to press them. This would need a small firmware and message addition (not built yet).
- **Pi in the sun:** heatsink or active cooler, a shaded enclosure, and a stable supply.

## 7. Bring-up order

1. Pi and ESP32 on the bench with the simulated hardware (already works).
2. Real hardware layer one subsystem at a time, drive first, with the other three still simulated.
3. Add the E-stop circuit and test it **before any motor runs on the real rail**.
4. Add the plate and screw mechanisms.
5. Add the drill **last**, because it is the noisiest and most dangerous part.
6. Whole-robot test on a flat mock roof, then on a real slope.

## 8. Decisions needed from you

1. The battery or power source and its voltage.
2. The drive motor type and size.
3. The plate and screw mechanism types.
4. What the crest and front sensors physically are.
5. Whether you want physical START and RESOLVED buttons on the robot.
6. Whether a contactor is acceptable, or a safety relay is required (depends on your supervisor and the course safety rules).

With answers to 1 to 4, the next step is a pin map in `config.h`, a parts list, and a wiring and power diagram. That is step A3 in `next_steps.md`.
