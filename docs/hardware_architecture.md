# Roofing Robot: Hardware and Compute Architecture

Decision record for what runs the control system. It goes with `complete_system_guide.md`, which describes the logic and messages. This file describes the hardware that runs them.

## Decision

A **Raspberry Pi 5 (8 GB)** is the Supervisor and vision computer. **Microcontrollers** run the real-time subsystems. A **hardware E-stop** sits outside both.

**Confirmed:** the microcontroller is an **ESP32** and the Pi-to-ESP32 link is **USB serial**. CAN was dropped unless vibration or noise problems appeared. **Update 2026-11-09:** the subsystems are spread out on the chassis, so the plan is now two ESP32 nodes (D17 in `design_concept.md`). CAN with a gateway ESP32 (the Pi stays on USB serial) is the leading option for the link between nodes, with RS-485 as the simpler alternative. Undecided until cable lengths and bench noise are known.

## Who runs what

| Job | Runs on | Why |
|---|---|---|
| Supervisor state machine, route map, fault log | Pi 5 (Python) | Normal software, files, logging |
| Live camera processing: plate arrived, plate and screw in spot, photo acceptance | Pi 5 | Image processing and video streaming |
| Operator interface, alerts, live feed | Pi 5 serving a web page | Viewed on a tablet or laptop over the Pi's Wi-Fi |
| Locomotion, Plate, Screw, Fastening subsystems | Microcontroller(s): ESP32, STM32 or Teensy | Hard timing, fast encoder counting, reliable I/O, fast boot |
| Stack light (status lamps the operator can see from across the roof) | Lamps driven by ESP32 outputs, set by the Supervisor with a `LIGHT` message | The operator may not have the screen in view. The ESP32 also does the flashing and shows flashing amber if the Pi goes quiet. |
| E-stop | Physical mushroom button cutting motor and drill power | Must work if software crashes. Also signals the Pi so it can log ESTOP |

Linux on the Pi is not real-time, so it never drives motors or counts encoder pulses directly.

## Links

- **Pi to microcontroller:** USB-serial to start. Move to CAN if vibration or noise is a problem. The message schema is the same for both.
- **Operator screen:** tablet or laptop over Wi-Fi to a web page on the Pi.
- **Start with one microcontroller** running all four subsystems as separate modules. Split to one board per subsystem later if needed. This keeps the "subsystems never talk to each other, only the Supervisor" rule.

## Safety and reliability requirements

- If a microcontroller stops hearing the Pi heartbeat, it stops the wheels and retracts the drill.
- Every `CMD_START` has a timeout. A silent subsystem raises a fault that goes to WAIT_OPERATOR.
- Replies echo the `msg_id` of the command they answer, so a late `DONE` from an old attempt is ignored.
- A repeated `CMD_START` must be safe to handle, since retries and RESOLVED both re-send it.
- The Pi is on a roof in the sun: heatsink or fan, shaded enclosure, stable power supply.
- Prefer booting from an SSD, or a read-only filesystem, to avoid SD card corruption. Write logs carefully.

## Alternatives considered

- **Pi only:** fine for an early prototype, but real-time parts should move off it.
- **Jetson Nano or Orin:** only if vision needs a neural network and the Pi 5 is too slow. Measure camera latency first (open item in the guide).
- **PLC:** robust, but overkill and awkward for the camera work.

For power, drivers, noise handling and the stack light, see the recommendation in `electrical_recommendations.md`.

## Still to decide

- Motor drivers, drill and torque sensing hardware, camera model and light.
- The stack light: which unit, its supply voltage (24 V is common), and the driver for each lamp (relay or MOSFET from an ESP32 pin). Three ESP32 outputs are reserved in `config.h` (`PIN_LIGHT_RED`, `PIN_LIGHT_AMBER`, `PIN_LIGHT_GREEN`). Mount it where it can be seen from anywhere on the roof, and not hidden by the camera enclosure.
- Review the message schema (`message_schema.md`) and the Supervisor code (`../supervisor/`, tested in simulation only).
- ESP32 firmware: **skeleton written** with the Arduino framework, PlatformIO and ArduinoJson (`../firmware/esp32/`, see `firmware_guide.md`). Compiles, not yet run on a board. Still to do: the pin map and the real hardware layer.
- The camera: which camera and light, where the vision code runs on the Pi, and how it feeds `CameraService` and the camera heartbeat.
- How the camera questions cross the USB link. Decided: `QUERY` and `ANSWER` messages through the Pi (see `message_schema.md`).
