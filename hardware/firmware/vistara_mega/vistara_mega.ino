// VISTARA-X low-level controller (Arduino Mega 2560)
//
// The navigation stack (FastAPI backend: SLAM, tracking, prediction, A*, pure
// pursuit, YOLOv8, Whisper) runs on a laptop carried by the robot. The laptop
// sends a body velocity command "V <v m/s> <w rad/s>" over USB (or Bluetooth
// through an HC-05 on Serial1). This firmware turns it into wheel speeds and
// enforces the safety rules locally, so the robot stays safe even if the laptop
// freezes or the link drops:
//
//   - command watchdog: no command for 500 ms -> stop
//   - ultrasonic ring: slow below 0.9 m, no forward motion below 0.3 m
//     (same thresholds as the backend's proximity layer); rear sensor guards reverse
//   - emergency stop input: latched until the button is released and "R" is sent
//   - battery monitor: half speed below 10.5 V, stop below 9.9 V (3S Li-ion)
//
// It sends one JSON telemetry line at 10 Hz (ultrasonic ranges, wheel speeds,
// encoder ticks, IMU, battery, safety state) to the port the last command came from.
//
// WOKWI_SIM = 1 builds for the Wokwi simulation: Wokwi has no DC motor with an
// encoder, so the motor outputs drive LEDs (brightness = PWM duty) and the wheel
// speed/encoder ticks come from a first-order motor model. The battery is a
// potentiometer. Set WOKWI_SIM to 0 for the real robot.
//
// AUTO_TOUR = 1 (Wokwi only) plays a 46 s script on its own that shows every
// safety rule: it sends the commands the laptop would send, walks a virtual
// person towards the robot, puts something behind it, drains the battery and
// presses the E-stop. Each step is explained in plain words in the serial
// monitor. The real sensors, knob and button still work during the tour.
// Typing V, S, D, R or L stops the tour; A starts it again.

#include <Arduino.h>
#include <Wire.h>
#include <stdlib.h>
#include <string.h>

#define WOKWI_SIM 1
#define AUTO_TOUR 1

// ---------------------------------------------------------------- pins
// Motor driver (Cytron MDD3A, or L298N with ENA/ENB jumpers fitted):
// PWM on input A = forward, PWM on input B = reverse. Timers 3 and 4, so
// tone() (timer 2) and millis() (timer 0) are not disturbed.
const uint8_t PIN_ML_A = 5, PIN_ML_B = 6;   // left motor  (M1A, M1B)
const uint8_t PIN_MR_A = 7, PIN_MR_B = 8;   // right motor (M2A, M2B)

// Hall encoders: channel A on an external interrupt, channel B gives direction
const uint8_t PIN_ENC_L_A = 2, PIN_ENC_L_B = 24;
const uint8_t PIN_ENC_R_A = 3, PIN_ENC_R_B = 25;

// MPU6050 on the hardware I2C pins 20 (SDA) and 21 (SCL)
const uint8_t PIN_BATTERY = A0;             // battery divider (or Wokwi potentiometer)
const uint8_t PIN_ESTOP = 26;               // E-stop NO contact to GND, LOW = pressed
const uint8_t PIN_BUZZER = 28;
const uint8_t PIN_STATUS_LED = 13;

// Ultrasonic ring: 6 HC-SR04 at 0, +40, -40, +90, -90, 180 degrees
enum { US_FRONT, US_FRONT_LEFT, US_FRONT_RIGHT, US_LEFT, US_RIGHT, US_REAR, US_COUNT };
const char *const US_NAME[US_COUNT] = {"front", "front_left", "front_right", "left", "right", "rear"};
const uint8_t US_TRIG[US_COUNT] = {30, 32, 34, 36, 38, 40};
const uint8_t US_ECHO[US_COUNT] = {31, 33, 35, 37, 39, 41};
// Consecutive pings come from sensors that face away from each other, so a late
// echo of one ping is not heard by the next sensor.
const uint8_t US_ORDER[US_COUNT] = {US_FRONT, US_REAR, US_FRONT_LEFT, US_RIGHT, US_FRONT_RIGHT, US_LEFT};

// ---------------------------------------------------------------- robot parameters
const float WHEEL_DIAMETER = 0.100;       // m
const float TRACK_WIDTH = 0.46;           // m, wheel centre to wheel centre
const float WHEEL_MAX_SPEED = 0.93;       // m/s at 12 V (178 rpm gearmotor)
const float MAX_ACCEL = 0.5;              // m/s^2 per wheel (robot carries a laptop)
const float TICKS_PER_REV = 616.0;        // 11 PPR x 56:1 gearbox, channel A rising edges
const float US_MAX_RANGE = 2.0;           // m, same as the simulated ultrasonic ring
const unsigned long US_TIMEOUT_US = 12000; // echo of a 2 m target takes 11.7 ms
const unsigned long CMD_TIMEOUT_MS = 500;
const float BAT_LOW = 10.5, BAT_CRITICAL = 9.9;  // V, 3S Li-ion
const float BAT_DIVIDER = (100.0 + 47.0) / 47.0; // 100k / 47k divider: 12.6 V -> 4.03 V

float slowDistance = 0.9, stopDistance = 0.3;    // m, changeable with "L <slow> <stop>"

// ---------------------------------------------------------------- state
enum SafetyState { WAIT_CMD, OK, OBSTACLE_SLOW, OBSTACLE_STOP, REAR_STOP, CMD_TIMEOUT, BATTERY_LOW, BATTERY_CRITICAL, ESTOP };
const char *const STATE_NAME[] = {"WAIT_CMD", "OK", "OBSTACLE_SLOW", "OBSTACLE_STOP", "REAR_STOP",
                                  "CMD_TIMEOUT", "BATTERY_LOW", "BATTERY_CRITICAL", "ESTOP"};
SafetyState state = WAIT_CMD;

// Defined up here because the Arduino builder puts its generated function
// prototypes (such as readPort's) above the first function, not at the top.
struct LineReader {
  char buf[48];
  uint8_t len = 0;
};
LineReader usbLine, btLine;

float usRange[US_COUNT] = {US_MAX_RANGE, US_MAX_RANGE, US_MAX_RANGE, US_MAX_RANGE, US_MAX_RANGE, US_MAX_RANGE};
uint8_t usNext = 0;

volatile long encTicks[2] = {0, 0};       // left, right

float cmdV = 0, cmdW = 0;                 // last command from the host
unsigned long lastCmdMs = 0;
bool demoMode = false;
bool estopLatched = false;
bool tourOn = AUTO_TOUR && WOKWI_SIM;     // "A" toggles the automatic tour
uint8_t tourStep = 0;
unsigned long tourStepMs = 0;             // 0 = tour not started yet
float tourRange[US_COUNT] = {US_MAX_RANGE, US_MAX_RANGE, US_MAX_RANGE, US_MAX_RANGE, US_MAX_RANGE, US_MAX_RANGE};
float tourBattery = 0;                    // virtual battery voltage, 0 = read the knob
bool tourEstop = false;                   // virtual E-stop press
const uint8_t TOUR_STEPS = 12;
const unsigned int TOUR_MS[TOUR_STEPS] = {3000, 4000, 7000, 3000, 3000, 4000, 4000, 4000, 3000, 4000, 4000, 3000};
bool telemetryOn = !tourOn;               // "T" toggles the 10 Hz JSON stream
SafetyState lastReported = WAIT_CMD;      // for the readable state-change lines
Stream *host = &Serial;                   // telemetry goes where the last command came from

float wheelTarget[2] = {0, 0};            // after safety limits, m/s
float wheelRamp[2] = {0, 0};              // after acceleration limit
float wheelMeasured[2] = {0, 0};
float wheelIntegral[2] = {0, 0};
int wheelPwm[2] = {0, 0};
long lastTicks[2] = {0, 0};
float outV = 0, outW = 0;

bool imuOk = false;
float gyroBiasZ = 0, yaw = 0, gz = 0, ax = 0, ay = 0;
float batteryV = 12.6;

// ---------------------------------------------------------------- encoders
#if !WOKWI_SIM
void encLeftIsr() { encTicks[0] += digitalRead(PIN_ENC_L_B) ? -1 : 1; }
void encRightIsr() { encTicks[1] += digitalRead(PIN_ENC_R_B) ? 1 : -1; }  // mirrored motor
#endif

// ---------------------------------------------------------------- ultrasonic
// One sensor per control cycle (blocks at most 12 ms), so each sensor is read
// every 120 ms (~8 Hz) while the control loop keeps its 50 Hz rate.
void pingNextSonar() {
  uint8_t i = US_ORDER[usNext];
  usNext = (usNext + 1) % US_COUNT;
  digitalWrite(US_TRIG[i], LOW);
  delayMicroseconds(2);
  digitalWrite(US_TRIG[i], HIGH);
  delayMicroseconds(10);
  digitalWrite(US_TRIG[i], LOW);
  unsigned long width = pulseIn(US_ECHO[i], HIGH, US_TIMEOUT_US);
  float r = width ? width * 0.000343f / 2.0f : US_MAX_RANGE;  // no echo in time = nothing within range
  r = min(r, tourRange[i]);  // the tour's virtual obstacle, if it is closer
  usRange[i] = constrain(r, 0.02f, US_MAX_RANGE);
}

// ---------------------------------------------------------------- IMU (MPU6050, raw registers)
bool imuWrite(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(0x68);
  Wire.write(reg);
  Wire.write(val);
  return Wire.endTransmission() == 0;
}

bool imuRead(int16_t out[7]) {
  Wire.beginTransmission(0x68);
  Wire.write(0x3B);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((uint8_t)0x68, (uint8_t)14) != 14) return false;
  for (uint8_t i = 0; i < 7; i++) {
    int16_t hi = Wire.read();
    out[i] = (hi << 8) | Wire.read();
  }
  return true;
}

void setupImu() {
  imuOk = imuWrite(0x6B, 0x00);  // wake up; +-2 g and +-250 deg/s defaults
  if (!imuOk) return;
  delay(50);
  // Gyro bias: average while the robot stands still at power-up.
  float sum = 0;
  int16_t raw[7];
  int n = 0;
  for (int i = 0; i < 100; i++) {
    if (imuRead(raw)) { sum += raw[6]; n++; }
    delay(3);
  }
  gyroBiasZ = n ? sum / n : 0;
}

void updateImu(float dt) {
  int16_t raw[7];
  if (!imuOk || !imuRead(raw)) { imuOk = false; return; }
  ax = raw[0] / 16384.0f * 9.81f;
  ay = raw[1] / 16384.0f * 9.81f;
  gz = (raw[6] - gyroBiasZ) / 131.0f * DEG_TO_RAD;
  yaw += gz * dt;
}

// ---------------------------------------------------------------- battery
void updateBattery() {
  float v = analogRead(PIN_BATTERY) * 5.0f / 1023.0f;
#if WOKWI_SIM
  // Potentiometer as state of charge: fully left = full (12.6 V), right = empty (9.0 V).
  float measured = tourBattery > 0 ? tourBattery : 12.6f - v / 5.0f * 3.6f;
#else
  float measured = v * BAT_DIVIDER;
#endif
  batteryV += (measured - batteryV) * 0.2f;  // light smoothing
}

// ---------------------------------------------------------------- motors
void setMotor(uint8_t pinA, uint8_t pinB, int pwm) {
  pwm = constrain(pwm, -255, 255);
  analogWrite(pinA, pwm > 0 ? pwm : 0);
  analogWrite(pinB, pwm < 0 ? -pwm : 0);
}

void stopMotors() {
  for (uint8_t i = 0; i < 2; i++) {
    wheelTarget[i] = wheelRamp[i] = wheelIntegral[i] = 0;
    wheelPwm[i] = 0;
  }
  setMotor(PIN_ML_A, PIN_ML_B, 0);
  setMotor(PIN_MR_A, PIN_MR_B, 0);
}

// ---------------------------------------------------------------- safety + kinematics
void applySafety() {
  float v = cmdV, w = cmdW;
  bool fresh = demoMode || (lastCmdMs && millis() - lastCmdMs <= CMD_TIMEOUT_MS);

  if (digitalRead(PIN_ESTOP) == LOW || tourEstop) estopLatched = true;

  if (estopLatched) {
    state = ESTOP; v = w = 0;
  } else if (batteryV < BAT_CRITICAL) {
    state = BATTERY_CRITICAL; v = w = 0;
  } else if (!fresh) {
    state = lastCmdMs ? CMD_TIMEOUT : WAIT_CMD; v = w = 0;
  } else {
    state = OK;
    float front = min(usRange[US_FRONT], min(usRange[US_FRONT_LEFT], usRange[US_FRONT_RIGHT]));
    if (v > 0) {
      if (front <= stopDistance) {
        v = 0; state = OBSTACLE_STOP;   // turning in place is still allowed
      } else if (usRange[US_FRONT] < slowDistance) {
        float f = (usRange[US_FRONT] - stopDistance) / (slowDistance - stopDistance);
        v *= max(f, 0.15f); state = OBSTACLE_SLOW;
      }
    } else if (v < 0 && usRange[US_REAR] <= stopDistance) {
      v = 0; state = REAR_STOP;
    }
    if (batteryV < BAT_LOW) {
      v *= 0.5f; w *= 0.5f;
      if (state == OK) state = BATTERY_LOW;
    }
  }

  // Differential drive: v = (vr + vl) / 2, w = (vr - vl) / track
  float vl = v - w * TRACK_WIDTH / 2, vr = v + w * TRACK_WIDTH / 2;
  float peak = max(fabs(vl), fabs(vr));
  if (peak > WHEEL_MAX_SPEED) { vl *= WHEEL_MAX_SPEED / peak; vr *= WHEEL_MAX_SPEED / peak; }
  wheelTarget[0] = vl;
  wheelTarget[1] = vr;
}

// ---------------------------------------------------------------- wheel speed control
void updateWheels(float dt) {
  bool hardStop = state == ESTOP || state == BATTERY_CRITICAL;
  long ticks[2];
  noInterrupts();
  ticks[0] = encTicks[0];
  ticks[1] = encTicks[1];
  interrupts();

  const float metresPerTick = PI * WHEEL_DIAMETER / TICKS_PER_REV;
  for (uint8_t i = 0; i < 2; i++) {
    float step = MAX_ACCEL * dt;
    // E-stop and empty battery cut immediately; everything else ramps down.
    wheelRamp[i] = hardStop ? 0 : wheelRamp[i] + constrain(wheelTarget[i] - wheelRamp[i], -step, step);

    wheelMeasured[i] = (ticks[i] - lastTicks[i]) * metresPerTick / dt;
    lastTicks[i] = ticks[i];

    // Feed-forward plus PI on the measured wheel speed
    float err = wheelRamp[i] - wheelMeasured[i];
    wheelIntegral[i] = constrain(wheelIntegral[i] + err * dt, -0.3f, 0.3f);
    float u = wheelRamp[i] / WHEEL_MAX_SPEED * 255.0f + 120.0f * err + 300.0f * wheelIntegral[i];
    if (fabs(wheelRamp[i]) < 0.005f) { u = 0; wheelIntegral[i] = 0; }
    wheelPwm[i] = constrain((int)round(u), -255, 255);
  }
  setMotor(PIN_ML_A, PIN_ML_B, wheelPwm[0]);
  setMotor(PIN_MR_A, PIN_MR_B, wheelPwm[1]);

  outV = (wheelMeasured[0] + wheelMeasured[1]) / 2;
  outW = (wheelMeasured[1] - wheelMeasured[0]) / TRACK_WIDTH;

#if WOKWI_SIM
  // First-order motor model (time constant 0.15 s) standing in for the
  // gearmotor + encoder that Wokwi cannot simulate.
  static float simSpeed[2] = {0, 0};
  static float simTickAccum[2] = {0, 0};
  for (uint8_t i = 0; i < 2; i++) {
    simSpeed[i] += (wheelPwm[i] / 255.0f * WHEEL_MAX_SPEED - simSpeed[i]) * dt / 0.15f;
    simTickAccum[i] += simSpeed[i] * dt / (PI * WHEEL_DIAMETER) * TICKS_PER_REV;
    long whole = (long)simTickAccum[i];
    simTickAccum[i] -= whole;
    encTicks[i] += whole;
  }
#endif
}

// ---------------------------------------------------------------- automatic tour (Wokwi)
// Called at the start of each step: clear the virtual inputs, then set the ones
// this step needs from its first moment.
void tourEnter(uint8_t step) {
  for (uint8_t i = 0; i < US_COUNT; i++) tourRange[i] = US_MAX_RANGE;
  tourBattery = 0;
  tourEstop = false;
  if (step == 0) { cmdV = cmdW = 0; lastCmdMs = 0; }
  if (step == 3) tourRange[US_FRONT] = 0.2;   // the person is still standing there
  if (step == 7) tourBattery = 10.2;
  if (step == 8) tourBattery = 9.6;
  if (step == 10) estopLatched = false;       // same as releasing the button and sending "R"
}

void tourAnnounce(Stream &o, uint8_t step) {
  o.println();
  o.println(F("=============================================================="));
  o.print(F("STEP ")); o.print(step + 1); o.print('/'); o.print(TOUR_STEPS); o.print(F("  "));
  switch (step) {
    case 0:
      o.println(F("Power on: the robot waits for the laptop"));
      o.println(F("  No speed command has arrived yet, so the motors stay off."));
      o.println(F("  Watch: blue LED blinks slowly, all motor LEDs off."));
      break;
    case 1:
      o.println(F("The laptop says: drive forward at 0.5 m/s"));
      o.println(F("  Both wheels turn forward. Speed rises gently (0.5 m/s^2 limit)."));
      o.println(F("  Watch: L FWD and R FWD (green) get brighter, blue LED solid."));
      break;
    case 2:
      o.println(F("A person walks towards the front of the robot"));
      o.println(F("  The front sensor distance drops from 2.0 m. Below 0.9 m the"));
      o.println(F("  robot slows down, at 0.3 m it stops, even though the laptop"));
      o.println(F("  still says 'drive'."));
      o.println(F("  Watch: green LEDs dim, then go off; buzzer beeps."));
      break;
    case 3:
      o.println(F("The person is still there: the robot turns in place"));
      o.println(F("  Driving forward is blocked, but turning on the spot is allowed,"));
      o.println(F("  so the laptop can look for another way."));
      o.println(F("  Watch: L REV (red) and R FWD (green) light together."));
      break;
    case 4:
      o.println(F("The path is clear again: drive forward"));
      o.println(F("  Watch: both green LEDs light again."));
      break;
    case 5:
      o.println(F("Reversing, then something appears behind the robot"));
      o.println(F("  The rear sensor guards reverse motion: at 0.3 m it stops."));
      o.println(F("  Watch: L REV and R REV (red) light, then go off."));
      break;
    case 6:
      o.println(F("The laptop freezes: commands stop arriving"));
      o.println(F("  The laptop normally sends a command every 50 ms. After 0.5 s"));
      o.println(F("  without one, the Arduino stops the robot by itself (watchdog)."));
      o.println(F("  Watch: green LEDs go off about 1.5 s into this step."));
      break;
    case 7:
      o.println(F("The battery is getting low (10.2 V)"));
      o.println(F("  Below 10.5 V the robot drives at half speed to get home safely."));
      o.println(F("  Watch: green LEDs at about half brightness."));
      break;
    case 8:
      o.println(F("The battery is empty (9.6 V)"));
      o.println(F("  Below 9.9 V the motors switch off to protect the battery."));
      o.println(F("  Watch: motor LEDs off, buzzer beeps."));
      break;
    case 9:
      o.println(F("Someone presses the EMERGENCY STOP"));
      o.println(F("  Motors cut instantly, no slow ramp-down. The stop is latched:"));
      o.println(F("  the robot will not move again on its own."));
      o.println(F("  Watch: all motor LEDs off at once, fast beeping."));
      break;
    case 10:
      o.println(F("E-stop released and reset (the 'R' command)"));
      o.println(F("  Only after a deliberate reset does the robot drive again."));
      o.println(F("  Watch: green LEDs light again."));
      break;
    case 11:
      o.println(F("Tour finished: the laptop sends stop"));
      o.println(F("  The tour starts again in 3 s. Type S to stop it and try the"));
      o.println(F("  commands yourself, A to start it again."));
      break;
  }
  o.println(F("=============================================================="));
}

// Plays the current step: moves the virtual obstacles and sends the command the
// laptop would send, 50 times a second.
void tourUpdate(unsigned long now) {
  if (!tourOn) return;
  if (tourStepMs == 0 || now - tourStepMs >= TOUR_MS[tourStep]) {
    if (tourStepMs) tourStep = (tourStep + 1) % TOUR_STEPS;
    tourStepMs = now;
    tourEnter(tourStep);
    tourAnnounce(*host, tourStep);
  }
  float t = (now - tourStepMs) / 1000.0f;
  float v = 0, w = 0;
  bool send = true;
  switch (tourStep) {
    case 0: send = false; break;
    case 2: v = 0.5; tourRange[US_FRONT] = max(0.2f, 2.0f - 0.3f * t); break;  // person walks in at 0.3 m/s
    case 3: w = 1.0; break;
    case 5: v = -0.2; tourRange[US_REAR] = t < 1.5f ? US_MAX_RANGE : 0.2f; break;
    case 6: v = 0.5; send = t < 1.0f; break;
    case 9: v = 0.5; tourEstop = t >= 1.5f; break;
    case 11: break;
    default: v = 0.5; break;  // steps 1, 4, 7, 8, 10
  }
  if (send) { cmdV = v; cmdW = w; lastCmdMs = now; }
}

void stopTour(Stream &o) {
  tourOn = false;
  tourEnter(0);
  o.println(F("Tour stopped. You are in control now (type ? for the commands, A to restart the tour)."));
}

void printMotor(Stream &o, int pwm) {
  if (pwm == 0) { o.print(F("off    ")); return; }
  o.print(pwm > 0 ? F("FWD ") : F("REV "));
  int pct = abs(pwm) * 100 / 255;
  if (pct < 10) o.print(' ');
  if (pct < 100) o.print(' ');
  o.print(pct); o.print('%');
}

// Readable status line, twice a second during the tour
void tourStatus(Stream &o, unsigned long now) {
  o.print(F("  t=")); o.print((now - tourStepMs) / 1000.0f, 1); o.print(F("s  "));
  o.print(STATE_NAME[state]);
  for (uint8_t n = strlen(STATE_NAME[state]); n < 17; n++) o.print(' ');
  o.print(F("speed ")); o.print(outV, 2);
  o.print(F(" m/s | front ")); o.print(usRange[US_FRONT], 2);
  o.print(F(" m | rear ")); o.print(usRange[US_REAR], 2);
  o.print(F(" m | battery ")); o.print(batteryV, 1);
  o.print(F(" V | left motor ")); printMotor(o, wheelPwm[0]);
  o.print(F(" | right motor ")); printMotor(o, wheelPwm[1]);
  o.println();
}

// ---------------------------------------------------------------- serial commands
// V <v> <w>       body velocity (m/s, rad/s); must repeat at least every 500 ms
// S               stop now
// R               reset a latched E-stop (only once the button is released)
// L <slow> <stop> ultrasonic slow/stop distances (m)
// D               demo mode on/off: drive at 0.5 m/s without a host (Wokwi test)
// T               JSON telemetry on/off (state changes are always printed)
// A               automatic tour on/off (Wokwi only)
// ?               print help
void printHelp(Stream &o) {
  o.println(F("{\"help\":\"V <v> <w> | S | R | L <slow> <stop> | D | T | A | ?\"}"));
}

void printWhy(Stream &o) {
  switch (state) {
    case WAIT_CMD:         o.print(F("waiting for a command")); break;
    case OK:               o.print(cmdV || cmdW ? F("driving") : F("stopped, the command is zero")); break;
    case OBSTACLE_SLOW:    o.print(F("obstacle ")); o.print(usRange[US_FRONT], 2); o.print(F(" m ahead, slowing")); break;
    case OBSTACLE_STOP:    o.print(F("obstacle within ")); o.print(stopDistance, 2); o.print(F(" m ahead, stopped")); break;
    case REAR_STOP:        o.print(F("obstacle behind, reverse blocked")); break;
    case CMD_TIMEOUT:      o.print(F("no command for 0.5 s, stopped")); break;
    case BATTERY_LOW:      o.print(F("battery ")); o.print(batteryV, 1); o.print(F(" V, half speed")); break;
    case BATTERY_CRITICAL: o.print(F("battery ")); o.print(batteryV, 1); o.print(F(" V, motors off")); break;
    case ESTOP:            o.print(F("emergency stop pressed, send R after release")); break;
  }
}

// One readable line whenever the safety state changes, e.g.
// {"event":"state","state":"OBSTACLE_STOP","why":"obstacle within 0.30 m ahead, stopped"}
// or, during the tour:  >> OBSTACLE_STOP: obstacle within 0.30 m ahead, stopped
void reportStateChange() {
  if (state == lastReported) return;
  lastReported = state;
  Stream &o = *host;
  if (tourOn) {
    o.print(F("  >> ")); o.print(STATE_NAME[state]); o.print(F(": ")); printWhy(o); o.println();
    return;
  }
  o.print(F("{\"event\":\"state\",\"state\":\"")); o.print(STATE_NAME[state]);
  o.print(F("\",\"why\":\"")); printWhy(o);
  o.println(F("\"}"));
}

// Reads two numbers after the command letter. AVR sscanf has no %f, so strtod.
bool twoNumbers(char *s, float &a, float &b) {
  char *end;
  a = strtod(s, &end);
  if (end == s) return false;
  s = end;
  b = strtod(s, &end);
  return end != s;
}

void handleLine(char *s, Stream &port) {
  float a, b;
  host = &port;
  char c = toupper(s[0]);
  if (tourOn && strchr("VSDRL", c)) stopTour(port);  // a manual command takes over
  switch (s[0]) {
    case 'A': case 'a':
      if (!WOKWI_SIM) {
        port.println(F("{\"error\":\"the tour fakes obstacles, it only runs in the simulation\"}"));
      } else if (tourOn) {
        stopTour(port);
      } else {
        tourOn = true;
        demoMode = false;
        tourStep = 0;
        tourStepMs = 0;
      }
      break;
    case 'V': case 'v':
      if (twoNumbers(s + 1, a, b)) {
        cmdV = constrain(a, -0.5f, WHEEL_MAX_SPEED);
        cmdW = constrain(b, -2.0f, 2.0f);
        lastCmdMs = millis();
        demoMode = false;
      } else {
        port.println(F("{\"error\":\"usage: V <v_mps> <w_radps>\"}"));
      }
      break;
    case 'S': case 's':
      cmdV = cmdW = 0; demoMode = false; lastCmdMs = millis();
      break;
    case 'R': case 'r':
      if (digitalRead(PIN_ESTOP) == HIGH) {
        estopLatched = false;
        port.println(F("{\"event\":\"estop_reset\"}"));
      } else {
        port.println(F("{\"error\":\"release the E-stop button first\"}"));
      }
      break;
    case 'L': case 'l':
      if (twoNumbers(s + 1, a, b) && a > b && b > 0) { slowDistance = a; stopDistance = b; }
      else port.println(F("{\"error\":\"usage: L <slow_m> <stop_m>, slow > stop > 0\"}"));
      break;
    case 'D': case 'd':
      demoMode = !demoMode;
      cmdV = demoMode ? 0.5f : 0; cmdW = 0;
      port.print(F("{\"event\":\"demo\",\"on\":"));
      port.print(demoMode ? F("true") : F("false"));
      port.println('}');
      break;
    case 'T': case 't':
      telemetryOn = !telemetryOn;
      port.print(F("{\"event\":\"telemetry\",\"on\":"));
      port.print(telemetryOn ? F("true") : F("false"));
      port.println('}');
      break;
    case '?':
      printHelp(port);
      break;
  }
}

void readPort(Stream &port, LineReader &r) {
  while (port.available()) {
    char c = port.read();
    if (c == '\n' || c == '\r') {
      if (r.len) { r.buf[r.len] = 0; handleLine(r.buf, port); r.len = 0; }
    } else if (r.len < sizeof(r.buf) - 1) {
      r.buf[r.len++] = c;
    }
  }
}

// ---------------------------------------------------------------- telemetry + indicators
void sendTelemetry() {
  Stream &o = *host;
  o.print(F("{\"t\":")); o.print(millis());
  o.print(F(",\"state\":\"")); o.print(STATE_NAME[state]);
  o.print(F("\",\"cmd\":[")); o.print(cmdV, 2); o.print(','); o.print(cmdW, 2);
  o.print(F("],\"out\":[")); o.print(outV, 2); o.print(','); o.print(outW, 2);
  o.print(F("],\"wheel\":[")); o.print(wheelMeasured[0], 2); o.print(','); o.print(wheelMeasured[1], 2);
  o.print(F("],\"pwm\":[")); o.print(wheelPwm[0]); o.print(','); o.print(wheelPwm[1]);
  noInterrupts();
  long l = encTicks[0], r = encTicks[1];
  interrupts();
  o.print(F("],\"enc\":[")); o.print(l); o.print(','); o.print(r);
  o.print(F("],\"us\":{"));
  for (uint8_t i = 0; i < US_COUNT; i++) {
    if (i) o.print(',');
    o.print('"'); o.print(US_NAME[i]); o.print(F("\":")); o.print(usRange[i], 2);
  }
  o.print(F("},\"imu\":{\"ok\":")); o.print(imuOk ? F("true") : F("false"));
  o.print(F(",\"yaw\":")); o.print(yaw, 3);
  o.print(F(",\"gz\":")); o.print(gz, 3);
  o.print(F(",\"ax\":")); o.print(ax, 2);
  o.print(F(",\"ay\":")); o.print(ay, 2);
  o.print(F("},\"bat\":")); o.print(batteryV, 2);
  o.print(F(",\"estop\":")); o.print(estopLatched ? F("true") : F("false"));
  o.println('}');
}

void updateIndicators(unsigned long nowMs) {
  bool alarm = estopLatched || state == OBSTACLE_STOP || state == BATTERY_CRITICAL;
  static bool toneOn = false;
  bool beep = alarm && (nowMs / 250) % 2 == 0;
  if (beep != toneOn) {
    if (beep) tone(PIN_BUZZER, estopLatched ? 1800 : 1000);
    else noTone(PIN_BUZZER);
    toneOn = beep;
  }
  // LED: solid = driving normally, fast blink = alarm, slow blink = idle / waiting
  bool led;
  if (alarm) led = (nowMs / 100) % 2;
  else if (state == OK || state == OBSTACLE_SLOW) led = true;
  else led = (nowMs / 500) % 2;
  digitalWrite(PIN_STATUS_LED, led);
}

// ---------------------------------------------------------------- main
void setup() {
  Serial.begin(115200);   // USB to the laptop
  Serial1.begin(115200);  // optional HC-05 Bluetooth module (set to 115200 baud)
  pinMode(PIN_ML_A, OUTPUT); pinMode(PIN_ML_B, OUTPUT);
  pinMode(PIN_MR_A, OUTPUT); pinMode(PIN_MR_B, OUTPUT);
  stopMotors();
  pinMode(PIN_ESTOP, INPUT_PULLUP);
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_STATUS_LED, OUTPUT);

  for (uint8_t i = 0; i < US_COUNT; i++) {
    pinMode(US_TRIG[i], OUTPUT);
    digitalWrite(US_TRIG[i], LOW);
    pinMode(US_ECHO[i], INPUT);
  }

#if !WOKWI_SIM
  pinMode(PIN_ENC_L_A, INPUT_PULLUP); pinMode(PIN_ENC_L_B, INPUT_PULLUP);
  pinMode(PIN_ENC_R_A, INPUT_PULLUP); pinMode(PIN_ENC_R_B, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_L_A), encLeftIsr, RISING);
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_R_A), encRightIsr, RISING);
#endif

  Wire.begin();
#if defined(WIRE_HAS_TIMEOUT)
  Wire.setWireTimeout(3000, true);  // a missing IMU must not hang the controller
#endif
  setupImu();
  for (uint8_t i = 0; i < 5; i++) updateBattery();

  Serial.print(F("{\"event\":\"boot\",\"firmware\":\"vistara-mega 1.0\",\"sim\":"));
  Serial.print(WOKWI_SIM ? F("true") : F("false"));
  Serial.print(F(",\"imu\":"));
  Serial.print(imuOk ? F("true") : F("false"));
  Serial.println('}');
  printHelp(Serial);
  if (tourOn) {
    Serial.println();
    Serial.println(F("AUTOMATIC TOUR: the robot now shows every safety rule on its own,"));
    Serial.println(F("12 steps in about 46 s, then it repeats. Just watch the LEDs and read here."));
    Serial.println(F("The LEDs are the motors: green = wheel forward, red = wheel backward,"));
    Serial.println(F("brighter = faster. Type S to stop the tour, A to start it again."));
  }
}

void loop() {
  static unsigned long lastControlMs = 0, lastTelemetryMs = 0;
  unsigned long now = millis();

  readPort(Serial, usbLine);
  readPort(Serial1, btLine);

  if (now - lastControlMs >= 20) {             // 50 Hz control loop
    float dt = min((now - lastControlMs) / 1000.0f, 0.05f);  // first pass after boot
    lastControlMs = now;
    tourUpdate(now);
    updateImu(dt);
    updateBattery();
    applySafety();
    reportStateChange();
    updateWheels(dt);
    updateIndicators(now);
    pingNextSonar();
  }

  if (now - lastTelemetryMs >= 100) {          // 10 Hz telemetry, like the backend sensors
    lastTelemetryMs = now;
    if (telemetryOn) sendTelemetry();
  }

  static unsigned long lastStatusMs = 0;
  if (tourOn && now - lastStatusMs >= 500) {   // readable status line during the tour
    lastStatusMs = now;
    tourStatus(*host, now);
  }
}
