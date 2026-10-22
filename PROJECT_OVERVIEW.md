# VISTARA-X: Project Overview

**Vision-Based Autonomous Navigation System**: *Beyond Seeing. Into Understanding.*
Team Hack01: Ritesh Kumar (Backend & AI/ML), Kainat Afrazi (Frontend). Built for Hack in Hills ’26.

---

## 1. The main purpose in one paragraph

VISTARA-X is the "brain" of an indoor or campus delivery robot. It lets a robot **move safely among people**: it maps the space, understands where a person asks it to go (by voice or text, in Hindi or English), plans a route, predicts where people around it are about to walk, and slows down, waits or steps aside **before** a conflict happens. If no safe route exists, it says so instead of forcing its way.

The whole system runs in a realistic simulation today. That lets the navigation software be built, tested and measured before anyone buys robot hardware.

> **VISTARA-X doesn't just detect obstacles. It predicts potential navigation conflicts and plans ahead.**

---

## 2. The problem it solves

Robots that work around people (in hospitals, warehouses, campuses, offices) face five everyday problems:

| Problem | What goes wrong with a simple robot |
|---|---|
| People move unpredictably | A robot that only reacts to what is in front of it brakes late, comes too close, or gets walked into. |
| The map is not always known | Someone must survey and draw the building before the robot can work. |
| Telling the robot where to go is hard | Coordinates and touchscreens on the robot do not suit nurses, visitors or staff who speak Hindi. |
| Not everyone can hear alarms | Beeps and spoken warnings exclude deaf and hard-of-hearing staff and visitors. |
| Failures are hidden | Robots that silently get stuck, or pretend to keep trying, cannot be trusted. |

VISTARA-X addresses each of these. Section 4 shows how, and section 6 lists what is still needed before real deployment.

---

## 3. How it works

The robot repeats one loop 20 times per second:

```text
Listen → Sense → Map → Track → Predict → Assess risk → Decide → Plan → Move → Monitor → Replan
```

| Stage | What happens | Technology |
|---|---|---|
| Listen | A spoken or typed command becomes a structured intent with a validated destination | Whisper (local speech-to-text), deterministic Hindi/English/Hinglish parser |
| Sense | Camera, depth, 360° LiDAR, ultrasonic ring, IMU, wheel odometry (all simulated, with realistic noise) | Python sensor models, PyBullet rendering |
| Map | The robot builds its own map and corrects its position | Log-odds occupancy grid, correlative scan-matching SLAM, frontier exploration |
| Track | Moving objects get stable IDs, speed and direction | LiDAR segmentation against a prior map, Kalman filters |
| Predict | Where each object will be in 0.5, 1, 2 and 3 s, with uncertainty | Constant-velocity motion model |
| Assess risk | LOW / MEDIUM / HIGH and time to conflict, from explicit rules | Rollout of the robot's route against predictions |
| Decide | Continue, slow, crawl, wait, step aside or replan, with a written reason | Sampling-based speed planner and evasion |
| Plan | Shortest safe route on the map | A\* on an inflated occupancy grid |
| Move | Smooth driving along the route | Pure-pursuit controller |
| Monitor | Three independent safety layers, plus an emergency stop that never depends on speech | Route check, LiDAR/ultrasonic proximity stop, physics veto |

The operator sees everything live in a web dashboard (React and Three.js). It shows a 3D digital twin, maps, predictions, risk, commands, alerts and test results, fed by a FastAPI backend over WebSocket.

---

## 4. Why it is useful in the real world

### 4.1 Where robots like this are used today

Autonomous mobile robots already work in many warehouses and factories. Delivery robots carry medicines and samples in some hospitals, and small delivery robots run on some university campuses. VISTARA-X targets exactly these settings, and each one is modelled as a simulation scenario:

| Setting | Real-world task | Scenario in VISTARA-X |
|---|---|---|
| Hospital | Deliver medicines, lab samples, linen and meals between departments, so nurses spend more time with patients | `hospital`: corridor, wards, pharmacy, lab, ICU, a nurse and a visitor who does not give way |
| Campus | Carry food and parcels between buildings | `campus`: six buildings, trees, benches, a fountain, students crossing |
| Warehouse / factory | Move goods between racks and docks without fixed tracks | `warehouse`: racking aisles, pallets, a patrolling worker |
| Shared corridors (airports, malls, offices) | Move through crowds without bumping into people | `crossing`: a person crossing without giving way, a cart that turns |

### 4.2 What each capability is worth to a real user

| Capability | Real-world benefit |
|---|---|
| **Predictive avoidance** | Fewer collisions and near misses with people. It also keeps a comfortable distance, which matters for patients, the elderly and children. |
| **Stepping aside** | In narrow corridors the robot gets out of the way of someone walking towards it, as a polite person would. |
| **Self-mapping (SLAM)** | Setup is faster: the robot can explore and map a new floor itself, and maps can be exported to and imported from standard ROS tools. |
| **Voice and text commands in Hindi and English** | Anyone can send the robot ("Robot ko pharmacy tak le jao") without training or a special app, which matters for Indian hospitals and campuses. |
| **Confirm before moving, honest "Blocked"** | No surprise movements: the robot shows what it understood first, and says when a place cannot be reached. |
| **Accessible, text-first interface** | Deaf and hard-of-hearing staff can operate the robot fully. Every alert is visual, with text and an icon. |
| **Emergency stop independent of AI** | A safety action never waits on speech recognition, the network or a model. |
| **Explanations for every decision** | Staff and auditors can see *why* the robot slowed or stopped. This builds trust and helps investigate incidents. |
| **Simulation-first development** | Navigation is tested and measured in software before expensive hardware is bought. |

### 4.3 Measured results (in simulation)

| What was measured | Result |
|---|---|
| Predictive vs reactive robot, 9 crossing variants each | Goal reached 9/9 vs 7/9; collisions 0 vs 2; near misses 0 vs 3; worst-case closest approach 0.60 m vs contact |
| Cost of predicting | About 1.5 s longer per mission (26.4 s vs 24.9 s) |
| Localisation over a long loop | SLAM error stayed at 8–10 cm, while wheel odometry alone drifted to 140 cm |
| Prediction accuracy | Mean error of the 1 s prediction: 0.20 m (largest when objects turn) |
| Voice commands | Whisper `base` on a laptop CPU: about 3–6 s per command |
| Automated tests | 155 backend tests and 33 browser end-to-end tests |

These come from one simulated environment with scripted motion. They show the approach works and can be measured. They are not a real-world safety certification.

---

## 5. What exists today (honest status)

| Status | What |
|---|---|
| **Working (in simulation)** | Everything in section 3: mapping, tracking, prediction, risk, predictive and reactive avoidance, evasion, A\*, voice/text commands, accessibility, 3D twin, evaluation script, demos |
| **Simulated** | All sensors, robot motion, people and obstacles, the buildings |
| **Working (operations)** | Delivery tasks with PIN proof, priority queue, battery and charging, automatic doors, quiet/slow zones, notifications and webhook, reports and CSV, optional access keys with audit log |
| **Not done** | Real robot hardware, ROS 2 integration, lifts and multi-floor maps, multi-robot fleets, sign-language recognition, learned trajectory prediction, field trials, certification |

---

## 6. Real-world aspects: what is built and what still needs hardware

The real-world aspects identified for VISTARA-X are listed below with their current status. **Built** means it exists in the software, runs in the simulation and is covered by automated tests. **Not built** means it cannot honestly be done without hardware, real data or certification work; the reason is given.

### 6.1 Doing real jobs

| # | Aspect | Status | What exists |
|---|---|---|---|
| 1 | **Delivery tasks** | Built | Pickup → *load confirmed* → drop-off → recipient enters a 4-digit PIN → *delivered*, with a timeline and proof of delivery. Requested from the Operations panel, the API, or by voice/text: *"Pharmacy se Ward B tak dawai le jao"*. |
| 2 | **Queue and priorities** | Built | Urgent → normal → low, then oldest first. The robot starts the next job by itself when idle. A failed pickup is retried once. A manual mission always takes precedence. |
| 3 | **Battery and charging** | Built (simulated) | Charge drops with distance and time. Below 30% the robot returns to the charging dock after its job; below 15% it abandons a pickup leg (re-queued), but finishes a drop-off it has started. It charges to 95% and resumes. Rates are demo-accelerated. |
| 4 | **Automatic doors** | Built (simulated) | Hospital doorways have sliding doors that open for the robot (2 m) and for people (1.6 m), then close after 2.5 s. The planner treats doors as passable; LiDAR, physics and the safety veto treat a closed door as solid, so the robot waits for it to open. |
| 5 | **Lifts and multi-floor** | Not built | The engine has one floor. Lifts need a building-system interface and multi-floor maps. |
| 6 | **Fleet of several robots** | Not built | The engine controls one robot. A fleet needs multi-robot simulation, shared traffic rules and task assignment across robots. |

### 6.2 People and trust

| # | Aspect | Status | What exists |
|---|---|---|---|
| 7 | **Social rules: quiet and slow zones** | Built | Speed-limited zones: hospital wards at 0.4 m/s, ICU at 0.35 m/s, the campus plaza at 0.5 m/s, the warehouse loading dock at 0.5 m/s. They are drawn on the 2D and 3D maps. Also built: giving way through prediction, and stepping aside. Keep-right lane rules are not built. |
| 8 | **Notifications** | Built | Every step (queued, started, arrived, loaded, delivered, failed, low battery) notifies the requester, staff or recipient in the app. If `VISTARA_WEBHOOK_URL` is set, each notification is also POSTed as JSON, so it can be connected to an SMS, WhatsApp or chat gateway. No external message is sent unless that URL is configured. |
| 9 | **More Indian languages** | Not built | Whisper can transcribe Marathi, Tamil, Bengali and others, but the command parser needs vocabulary for each, and there is no test audio to validate it. Hindi, English and Hinglish are supported. |
| 10 | **Sign language** | Not built | There is no validated sign-language model. Deaf users are supported with text input and visual alerts. |

### 6.3 Operations, security and safety assurance

| # | Aspect | Status | What exists |
|---|---|---|---|
| 11 | **Logs and reports** | Built | Each finished delivery is appended to `backend/operations/deliveries.jsonl`. The report (`GET /operations/report`, Operations panel) shows delivered, failed and cancelled counts, mean delivery time, distance, collisions, near misses and deliveries per day. It also downloads as CSV. |
| 12 | **Login, roles and audit trail** | Built (optional) | Set `VISTARA_OPERATOR_KEY` and/or `VISTARA_ADMIN_KEY`, and then: viewing is open; changes need an operator key; resets, parameters, map import and operations settings need the admin key. **The emergency stop never needs a key.** Every change is recorded in an audit log (`GET /audit`, admin only) and in `audit.jsonl`. |
| 13 | **Safety standards** | Started, not certified | A preliminary hazard log is below (section 6.5). Conformity with ISO 3691-4 or ISO 13482 needs a full risk assessment, safety-rated hardware and independent testing. |
| 14 | **Privacy** | Built by design | Camera frames and voice recordings are processed in memory and never written to disk. Speech recognition runs locally (Whisper), so no audio leaves the machine unless the operator chooses the browser speech engine. No analytics, no cookies. |

### 6.4 Hardware and intelligence (needs a robot or real data)

| # | Aspect | Status | Why not yet |
|---|---|---|---|
| 15 | ROS 2 bridge and a real robot base | Not built | Needs ROS 2 and a robot. The backend modules are separated along the same lines (scan, odometry, velocity command), and the README has a setup guide. |
| 16 | Real sensor tuning | Not built | Needs recorded data from real LiDAR and cameras (glass, mirrors, uneven floors). |
| 17 | Safety-rated emergency stop | Not built | Must be a hardware circuit; a software stop alone is never enough on a real machine. |
| 18 | Learned trajectory prediction | Not built | Needs real pedestrian trajectories. The rule-based predictor would stay as a fallback. |
| 19 | Loop closure for large buildings | Not built | Needed for maps much larger than the 20 × 12 m test areas. |

### 6.5 Preliminary hazard log

| Hazard | Cause | Mitigation in VISTARA-X | Remaining risk / next step |
|---|---|---|---|
| Robot hits a person | Person moves into the route | Prediction and early slowing; stepping aside; LiDAR/ultrasonic slow at 0.9 m and stop at 0.3 m; physics veto at 5 cm; quiet zones | A person can still walk into a stopped robot. Needs real-world validation and limits on speed and force. |
| Robot hits a fixed object | Map error or sensor gap | A\* on an inflated map, route re-validation, proximity stop, safety veto | Glass and black surfaces are invisible to LiDAR. Needs bumpers and sensor fusion on hardware. |
| Robot traps someone at a doorway | Door closes on a person or the robot | Doors stay open while anyone is within 1.6 m and for 2.5 s afterwards | Real doors need their own certified sensors. |
| Wrong delivery | Item collected by the wrong person | Recipient PIN; 3 wrong tries alert the operator | Medicines need stronger identity checks (badge, signature). |
| Unauthorised control | Someone sends commands | Optional operator/admin keys, roles, audit log, rate limiting | Needs TLS, real user accounts and network isolation in deployment. |
| Robot stops in an unsafe place | Battery empty | Automatic return below 30%; pickups abandoned below 15% | Real battery behaviour must be measured. |
| Misunderstood voice command | Speech recognition error | Transcript shown; confirmation before moving; unknown places are never guessed; stop does not depend on speech | Accents and noise need field testing. |

---

## 7. Who would use it and how it could be offered

| User | Value |
|---|---|
| Hospitals and clinics | Staff time saved on routine deliveries; safe movement near patients; Hindi/English voice requests |
| Warehouses and factories | Flexible material transport without floor tracks; fewer near misses with workers |
| Universities and large campuses | Food and parcel delivery between buildings |
| Robotics teams and researchers | A ready simulation and evaluation setup to test navigation and prediction ideas before building hardware |

Possible model: offer the navigation stack as software, licensed per robot or as Robotics-as-a-Service. The simulation and evaluation tools would also be available for teams testing their own robots. This comes from the team's pitch deck and is not market-validated.

---

## 8. How to see it

1. Start the backend: `backend\start.bat`, or `python -m uvicorn app.main:app --port 8000` in `backend/`.
2. Start the frontend: `frontend\start.bat`, or `npm run dev` in `frontend/`.
3. Open `http://localhost:5173/mission`.
4. Click **Run predictive demo**, or load **Hospital ward** and type *Robot ko pharmacy tak le jao*, then confirm.
5. For a real job: in **Delivery operations**, request *medicine* from **Pharmacy** to **Ward B** (or say *Pharmacy se Ward B tak dawai le jao*). Watch the robot open the doors and slow down in the ward. Confirm loading, then enter the PIN at the drop-off.

Full technical details, setup and the judge guide are in [README.md](README.md). A simple Hinglish summary is in [SIMPLE.md](SIMPLE.md).
