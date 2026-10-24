# Wokwi simulation: kaise check karein ki sab kaam kar raha hai

Yeh guide step by step batati hai ki VISTARA-X ka Arduino Mega circuit Wokwi mein kaise chalana hai aur har test mein kya dikhna chahiye. Har test ke saamne ☐ hai. Test pass ho jaaye toh tick kar do.

---

## 1. Setup (5 minute)

1. [wokwi.com](https://wokwi.com) kholo, login karo, phir **New Project → Arduino Mega** chuno.
2. `sketch.ino` tab mein sab kuch delete karke [firmware/vistara_mega/vistara_mega.ino](firmware/vistara_mega/vistara_mega.ino) ka poora code paste karo.
3. `diagram.json` tab mein bhi sab delete karke [firmware/vistara_mega/diagram.json](firmware/vistara_mega/diagram.json) paste karo. Circuit screen pe aa jaayega.
4. Code mein check karo ki `#define WOKWI_SIM 1` hai. Simulation ke liye yeh **1** hi hona chahiye.
5. **Save** dabao, phir **Share** se link copy kar lo. Yahi link README aur PPT mein daalna hai.
6. Green **▶ Start** dabao. Neeche **Serial Monitor** khul jaayega. Commands yahin type karke Enter dabana hai.

---

## 1.5 Sabse aasaan: automatic tour (kuch type nahi karna)

Code mein `#define AUTO_TOUR 1` hai. Start dabate hi robot **khud** saare safety rules ek-ek karke dikhata hai: 12 steps, kul ~46 second, phir dobara shuru. Tumhe sirf LEDs dekhni hain aur Serial Monitor padhna hai.

Har step shuru hone par aisa box aata hai:

```
==============================================================
STEP 3/12  A person walks towards the front of the robot
  The front sensor distance drops from 2.0 m. Below 0.9 m the
  robot slows down, at 0.3 m it stops, even though the laptop
  still says 'drive'.
  Watch: green LEDs dim, then go off; buzzer beeps.
==============================================================
  t=0.5s  OK               speed 0.50 m/s | front 1.85 m | rear 2.00 m | battery 12.6 V | left motor FWD  55% | right motor FWD  55%
  >> OBSTACLE_SLOW: obstacle 0.87 m ahead, slowing
  >> OBSTACLE_STOP: obstacle within 0.30 m ahead, stopped
```

- **Box** batata hai ki is step mein kya ho raha hai aur kaunsi LED dekhni hai.
- **`t=...` line** har 0.5 s aati hai: robot ki state, speed, aage aur peeche ki doori, battery, aur dono motors (FWD/REV aur kitne %).
- **`>>` line** tab aati hai jab robot ka faisla badalta hai, reason ke saath.

| Step | Kya hota hai | LEDs |
|---|---|---|
| 1 | Power on, laptop ke command ka wait | Blue blink, motors off |
| 2 | Laptop: aage chalo 0.5 m/s | Dono green tez hoti hain |
| 3 | Ek insaan saamne se aata hai (2.0 m → 0.2 m) | Green dheemi, phir off, buzzer |
| 4 | Insaan abhi bhi khada hai, robot jagah pe ghoomta hai | L REV (red) + R FWD (green) |
| 5 | Raasta saaf, phir chalo | Dono green |
| 6 | Peeche jaate hue peeche kuch aa gaya | Dono red, phir off |
| 7 | Laptop hang, commands band | ~1.5 s baad green off |
| 8 | Battery kam (10.2 V) | Green aadhi brightness |
| 9 | Battery khatam (9.6 V) | Off, buzzer |
| 10 | EMERGENCY STOP dabaya | Turant sab off, tez beep |
| 11 | E-stop chhoda aur reset kiya | Green phir on |
| 12 | Tour khatam, 3 s mein dobara | Off |

Tour ke dauran bhi asli sensor slider, battery knob aur E-STOP button kaam karte hain. **`S`** (ya koi bhi `V`, `D`, `R`, `L`) type karte hi tour ruk jaata hai aur control tumhare paas aa jaata hai. **`A`** se tour phir shuru hota hai. Neeche wale manual tests tour rok ke karne hain.

> Tour sirf simulation mein chalta hai (`WOKWI_SIM 1`), kyunki isme obstacles nakli hain. Asli robot pe `A` command error deta hai.

---

## 2. Screen pe kya kya hai

Robot ka **front right side** ki taraf hai.

| Part | Pin | Simulation mein kya hai |
|---|---|---|
| 6 ultrasonic sensors (HC-SR04) | TRIG/ECHO 30–41 | Robot ke charon taraf distance naapte hain. Sensor pe click karo toh distance ka slider aata hai |
| MPU6050 IMU | D20/D21 (I2C) | Robot ka ghoomna (gyro) aur jhatka (accel). Click karke values badal sakte ho |
| **L FWD** (green, D5) | D5 | Left motor aage |
| **L REV** (red, D6) | D6 | Left motor peeche |
| **R FWD** (green, D7) | D7 | Right motor aage |
| **R REV** (red, D8) | D8 | Right motor peeche |
| **Status** (blue, D13) | D13 | Lagatar jale = chal raha hai · dheere blink = ruka hai / command ka wait · tez blink = alarm |
| E-STOP button | D26 | Emergency stop |
| Buzzer | D28 | Alarm pe beep karta hai |
| Battery knob (potentiometer) | A0 | Battery ki jagah hai. **Poora left = full (12.6 V)**, right ghumao toh battery kam hoti hai |

> Motor LED jitni tez jalti hai, motor utni tez chal rahi hai, kyunki LED ki brightness hi PWM speed hai. Asli robot mein yahi pins motor driver (MDD3A) mein jaate hain.

---

## 3. Serial Monitor ki line kaise padhein

Start karte hi aisi lines aati hain:

```
{"event":"boot","firmware":"vistara-mega 1.0","sim":true,"imu":true}
{"help":"V <v> <w> | S | R | L <slow> <stop> | D | T | ?"}
{"event":"state","state":"WAIT_CMD","why":"waiting for a command"}
{"t":1200,"state":"WAIT_CMD","cmd":[0.00,0.00],"out":[0.00,0.00],...,"us":{"front":2.00,...},"bat":12.60,"estop":false}
```

- **`event":"state"` wali line sabse important hai.** Yeh batati hai ki robot kya kar raha hai aur kyun, jaise `"why":"obstacle 0.20 m ahead, stopped"`. Yeh line sirf tab aati hai jab state badalti hai.
- Lambi `{"t":...}` line JSON telemetry hai, jo har second 10 baar aati hai. Yeh wahi data hai jo laptop ka backend padhta hai. Tour chalte waqt yeh **band** rehti hai. Tour rokne ke baad **`T`** type karke on/off kar sakte ho. State wali lines hamesha aati hain.

Telemetry mein kaam ki cheezein:

| Key | Matlab |
|---|---|
| `state` | Abhi ki safety state |
| `cmd` | Robot ko kya speed boli gayi (m/s, rad/s) |
| `out` | Safety check ke baad asli speed. `cmd` aur `out` ka farak hi safety layer ka kaam hai |
| `us` | 6 sensors ki distance metres mein. Max 2.00 m dikhata hai, 200 cm se zyada bhi 2.00 hi aayega |
| `bat` | Battery voltage |
| `estop` | E-stop latched hai ya nahi |

---

## 4. Commands

| Command | Kya karta hai |
|---|---|
| `D` | Demo mode on/off. Robot 0.5 m/s aage chalta hai. **Testing ke liye yahi use karo** |
| `V 0.3 0` | Speed command: 0.3 m/s aage, 0 rad/s turn. Sirf **0.5 s** chalega (neeche Test 7 dekho) |
| `S` | Turant stop, demo bhi band |
| `R` | E-stop reset. Pehle button chhodna zaroori hai |
| `L 1.2 0.5` | Slow aur stop ki distance badlo (metres mein) |
| `T` | Telemetry on/off |
| `?` | Help |

---

## 5. Manual tests (upar se neeche, isi order mein karo)

Pehle **`S`** type karke automatic tour roko. Shuru karne se pehle sab sensors **200 cm** pe hon (default yahi hota hai) aur battery knob **poora left** ho.

### ☐ Test 1: Boot
- **Karo:** ▶ Start dabao, tour ka box aate hi `S` type karo.
- **Dikhna chahiye:** start mein `"event":"boot"`, `"sim":true`, `"imu":true`. `S` ke baad robot ruka hua hai, blue LED aur motor LEDs band hain.
- `"imu":false` aaye toh IMU ki wiring galat hai, `diagram.json` dobara paste karo.

### ☐ Test 2: Chalna
- **Karo:** `D` type karo.
- **Dikhna chahiye:** `{"event":"demo","on":true}`, state `OK` ("driving"). **L FWD aur R FWD (dono green)** dheere-dheere ~1 second mein poori brightness pe aate hain. Blue LED lagatar jalti hai. Telemetry mein `out` ≈ `0.50`.
- Ek dum se nahi, dheere-dheere tez hona hi sahi hai, kyunki acceleration limit 0.5 m/s² hai.

### ☐ Test 3: Obstacle paas aaya, speed kam
- **Karo:** Demo chalte hue **FRONT 0°** sensor pe click karo, slider ko **60 cm** pe le jao.
- **Dikhna chahiye:** state `OBSTACLE_SLOW`, green LEDs dheemi ho jaati hain, `out` ≈ `0.25`.

### ☐ Test 4: Obstacle bahut paas, STOP
- **Karo:** Front slider ko **20 cm** pe le jao.
- **Dikhna chahiye:** state `OBSTACLE_STOP`, LEDs band, **buzzer beep-beep**, blue LED tez blink.
- **Phir karo:** Slider wapas **200 cm**. Robot khud phir chal padta hai, state `OK`.
- FRONT-LEFT ya FRONT-RIGHT ko 20 cm karke bhi try karo, robot tab bhi rukega.

### ☐ Test 5: Rukne ke baad bhi ghoom sakta hai
- **Karo:** Front sensor 20 cm pe rakho. `D` se demo band karo, phir `V 0 1` type karke 2–3 baar jaldi-jaldi Enter dabao.
- **Dikhna chahiye:** **L REV (red) aur R FWD (green)** jalte hain. Robot aage nahi jaa sakta, lekin apni jagah ghoom ke raasta dhoondh sakta hai.
- Test ke baad front sensor wapas 200 cm kar do.

### ☐ Test 6: Peeche ka sensor
- **Karo:** **REAR 180°** sensor ko 20 cm pe karo, phir `V -0.2 0` type karo.
- **Dikhna chahiye:** state `REAR_STOP`, red LEDs nahi jalte.
- Test ke baad rear sensor wapas 200 cm kar do.

### ☐ Test 7: Watchdog (laptop hang ho jaaye toh?)
- **Karo:** `S` dabao, phir sirf **ek baar** `V 0.5 0` type karo.
- **Dikhna chahiye:** green LEDs thodi der jalte hain, phir ~0.5 s mein band. State `CMD_TIMEOUT` ("no command for 0.5 s, stopped").
- **Yeh bug nahi hai.** Asli robot mein laptop har 50 ms mein command bhejta hai. Command aana band ho jaaye (laptop hang, cable nikal gayi) toh robot khud ruk jaata hai.

### ☐ Test 8: Emergency stop
- **Karo:** `D` se demo chalao, phir laal **E-STOP** button dabao.
- **Dikhna chahiye:** saari motor LEDs **turant** band (dheere-dheere nahi), state `ESTOP`, `"estop":true`, buzzer tez beep karta hai.

### ☐ Test 9: E-stop latched rehta hai
- **Karo:** Button chhod do, phir `D` type karo.
- **Dikhna chahiye:** state abhi bhi `ESTOP`, robot apne aap nahi chalta. Yeh safety ke liye zaroori hai.

### ☐ Test 10: E-stop reset
- **Karo:** `R` type karo, phir `D`.
- **Dikhna chahiye:** `{"event":"estop_reset"}`, robot phir chalne lagta hai.
- Button dabe hue `R` bhejoge toh error aayega: `"release the E-stop button first"`.

### ☐ Test 11: Battery kam
- **Karo:** Demo chalte hue battery knob ko **~60% right** ghumao.
- **Dikhna chahiye:** `bat` 10.5 se neeche, state `BATTERY_LOW`, green LEDs aadhi brightness pe.

### ☐ Test 12: Battery khatam
- **Karo:** Knob ko **~80% se zyada right** ghumao.
- **Dikhna chahiye:** `bat` 9.9 se neeche, state `BATTERY_CRITICAL`, motors band, buzzer beep.
- Test ke baad knob wapas poora left kar do.

### ☐ Test 13: IMU
- **Karo:** MPU6050 pe click karo, **gyro Z** ko 45 °/s pe set karo.
- **Dikhna chahiye:** telemetry mein `imu.gz` ≈ `0.785` aur `imu.yaw` badhta rehta hai.

### ☐ Test 14: Safety distance badalna
- **Karo:** `L 1.2 0.5` type karo, demo chalao, front sensor ko 100 cm pe le jao.
- **Dikhna chahiye:** 100 cm pe hi `OBSTACLE_SLOW` (pehle yeh 90 cm pe hota tha) aur 50 cm pe `OBSTACLE_STOP`.

---

## 6. Kuch gadbad ho toh

| Problem | Wajah / hal |
|---|---|
| `Build failed` | `.ino` poora paste nahi hua. Dobara poora copy karo |
| Start karne ke baad motor LEDs nahi jalti | Robot command ka wait kar raha hai (`WAIT_CMD`). `D` type karo |
| `V` command se robot 0.5 s mein ruk jaata hai | Watchdog sahi kaam kar raha hai (Test 7). Testing ke liye `D` use karo |
| `D` dabaya, robot nahi chala | State line dekho. `ESTOP` ho toh button chhod ke `R` bhejo. `OBSTACLE_STOP` ho toh koi sensor 30 cm se kam pe hai. `BATTERY_CRITICAL` ho toh knob left karo |
| Commands kaam nahi kar rahe | Serial Monitor ke input box mein type karke **Enter** dabao. Ek line mein ek command |
| Bahut zyada lines, kuch padh nahi pa rahe | `T` type karo |
| `"imu":false` | `diagram.json` dobara paste karo |

---

## 7. Judges ke liye 1 minute ka demo

**Sabse aasaan:** sirf ▶ Start dabao aur automatic tour chalne do. Woh 46 second mein saare rules dikha deta hai, aur Serial Monitor ke box har step khud samjhaate hain. Screen record karte hue LEDs aur Serial Monitor dono frame mein rakho.

Ya manual demo karna ho toh `S` se tour roko aur yeh 4 cheezein dikhao, isi order mein:

1. `T` dabao (screen saaf rahe), phir `D` → green LEDs jalti hain, robot **chal raha hai**.
2. Front sensor 20 cm → LEDs band, buzzer → **obstacle pe ruk gaya**.
3. Sensor wapas 200 cm → robot phir chala. Ab **E-STOP** dabao → sab turant band.
4. Button chhodo, `R`, phir `D` → **reset ke baad hi** robot phir chalta hai.

Dikhate waqt har baar Serial Monitor ki `"why"` line padh ke batao, jaise *"obstacle within 0.30 m ahead, stopped"*. Isse judges ko pata chalta hai ki robot har kaam ka reason deta hai.
