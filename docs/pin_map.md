# Pin map (draft)

Drafted 2026-11-09 from `firmware/esp32/src/hal.h` and `firmware/esp32/include/config.h`. This is a planning table, not a wiring diagram. Nothing here has been wired or tested. Its purpose is to answer three questions in one place: how many pins the robot needs, where each signal physically is, and how noise-sensitive it is. Those decide whether one ESP32 is enough (`next_steps.md` question 10, `electrical_recommendations.md`).

How to use it: fill in the **Location** column (where on the chassis the sensor or actuator is) and check the **Noise** column against bench results. Then copy the pin numbers into `config.h`.

## 1. Signals

Type: DI digital input, DO digital output, PWM, ADC analog input, ENC quadrature encoder, I2C shared bus. Pins is the count if every signal had its own GPIO. "In config.h" says whether `config.h` already has a `PIN_` define for it.

| Subsystem | `hal.h` function | Signal | Type | Pins | In config.h | Location | Noise |
|---|---|---|---|---|---|---|---|
| Shared | `setStackLight` | Red, amber, green lamps (relay or MOSFET) | DO | 3 | yes | | low |
| Shared | (not in `hal.h`) | E-stop state sense, so firmware can see the hardware E-stop | DI | 1 | no, proposed | | medium |
| Locomotion | `driveForward`, `turn`, `stopWheels`, `relocate` | Left and right motor PWM | PWM | 2 | yes | | high source |
| Locomotion | same | Left and right motor direction (depends on the driver chosen) | DO | 2 | no | | high source |
| Locomotion | `encoderMm`, `resetEncoder` | Wheel encoders, two wheels for differential drive | ENC | 4 | only A and B (one encoder) | | **high** |
| Locomotion | `headingDeg`, `resetHeading` | IMU on the shared I2C bus | I2C | 0 extra | no | | medium |
| Locomotion | `onCrest` | Cross-track sensor array (diamond, 4 sensors). 4 pins if analog, 0 extra if on I2C | ADC | 4 | one pin (`PIN_CREST_SENSOR`) | | **high** |
| Locomotion | `frontSensorOnCrest` | Front sensor | DI | 1 | yes | | medium |
| Plate | `platesAvailable` | Plate supply sensor | DI | 1 | yes | | low |
| Plate | `tripwirePlateDetected` | Tripwire sensor | DI | 1 | yes | | low |
| Plate | `feedPlate`, `stopFeed` | Feed actuator | DO | 1 | yes | | medium |
| Plate | `pushPlate` | Push actuator | DO | 1 | yes | | medium |
| Plate | `releasePlate` | Release actuator | DO | 1 | yes | | medium |
| Plate | `clearPlate` | Clear actuator | DO | 1 | **no, missing** | | medium |
| Screw | `screwsAvailable` | Screw supply sensor | DI | 1 | yes | | low |
| Screw | `loadScrew` | Load actuator | DO | 1 | yes | | medium |
| Screw | `clearScrew` | Clear actuator | DO | 1 | **no, missing** | | medium |
| Fastening | `drillStart` | Drill motor drive | PWM | 1 | yes | | high source |
| Fastening | `drillRetract` | Retract actuator | DO | 1 | **no, missing** | | medium |
| Fastening | `drillRetracted` | Retract switch | DI | 1 | yes | | medium |
| Fastening | `torqueNm` | Torque sensing (ADC or motor current sense) | ADC | 1 | yes | | **high** |

## 2. Totals

| Group | Pins |
|---|---|
| Shared (stack light, E-stop sense) | 4 |
| Locomotion | 13 |
| Plate | 6 |
| Screw | 3 |
| Fastening | 4 |
| **Total GPIO** | **30** |
| I2C bus (IMU, and the array if it uses I2C) | +2 (SDA, SCL), shared |

So about 32 pins in all, before spares. `config.h` has 19 pin defines today, so it is missing the second encoder, the motor directions, the three clear and retract actuators and the E-stop sense.

## 3. What the table suggests

- **Pin count is close to the limit for one board, not far over it.** Rough, unverified figures: a classic ESP32 dev board has about 25 usable GPIOs (several are input-only, or tied to flash or boot), and an ESP32-S3 board has about 35 to 40. Check the exact board's pinout before trusting these. Slow digital signals (supply sensors, switches, lamps, the clear actuators) can move to an I2C or SPI I/O expander if pins run short.
- **Board mismatch to settle.** `electrical_recommendations.md` says ESP32-S3, but `platformio.ini` builds for `board = esp32dev`, which is the classic ESP32. The pin counts above differ between them, so settle which board it is first.
- **The noise-critical signals are the encoders, the sensor array and the torque sensor, and the sources are the drive motors and the drill.** If those sit far from where they are read, that is the strongest case for a node beside them (or for a bus). Fill in the Location column to see which signals have a long run.
- **Things not in `hal.h` yet that the hardware will need:** E-stop sense, motor direction, and a second encoder. Add them to `hal.h` or `config.h` when the drive hardware is chosen.

## 4. Open items

| # | Question |
|---|---|
| P1 | Which board: ESP32 (classic) or ESP32-S3? |
| P2 | Motor driver type, which sets how many direction and PWM pins per motor |
| P3 | Does the sensor array read on analog pins or I2C? This depends on the sensor chosen in the bench test |
| P4 | Torque sensing method: dedicated sensor, or current sense on the drill driver |
| P5 | Physical location of every signal (Location column), once the chassis layout is fixed |
