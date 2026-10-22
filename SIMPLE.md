# VISTARA-X: Project mein kya-kya hai

**Ek line mein:** Computer ke andar bane warehouse (simulation) mein chalne waala robot. Ye chalte hue logon aur trolleys ki agli position ka **andaaza lagata hai** aur takraav hone se **pehle** dheema hota hai, rukta hai ya doosra raasta leta hai. Ye khud map banata hai, Hindi/English mein baat samajhta hai, safe raasta dhoondta hai, rukawat aane par rukta hai aur naya raasta bana leta hai, aur ise bina awaaz ke bhi poora chalaya ja sakta hai.

---

## 1. Robot ka dimaag (navigation)

- **A\* path planning:** grid map par sabse chhota safe raasta, aur chalne se pehle us raaste ki dobara jaanch.
- **Pure-pursuit controller:** robot raaste par smoothly chalta hai.
- **Replanning:** raasta block hua toh robot rukta hai, 0.3 second ruk kar naya raasta banata hai.
- **Honest "Blocked":** koi safe raasta na ho toh robot saaf batata hai aur hilta nahi.
- **Mission states:** idle, planning, navigating, replanning, paused, goal reached, blocked, stopped, error.

## 2. Predictive navigation (naya, sabse khaas)

**"VISTARA-X sirf rukawat dekhta nahi, takraav ka pehle se andaaza lagata hai."**

- **Pehchaanna:** LiDAR ke jo points jaani-pehchaani deewaron aur shelves par nahi padte, unhe jod kar "objects" banaye jaate hain.
- **Track karna:** har object ko ek ID milti hai (T1, T2...). Kalman filter uski speed aur disha naapta hai. Jo object dikhna band ho jaye, woh "uncertain" ho jaata hai, aur 1.5 second baad "lost".
- **Andaaza (prediction):** 0.5, 1, 2 aur 3 second baad object kahan hoga, uncertainty ke ghere ke saath. Ye map aur 3D dono mein dikhta hai.
- **Risk LOW / MEDIUM / HIGH:** likhe hue niyamon se. 1.5 s ke andar takraav ka andaaza ho toh HIGH, 3 s ke andar ho toh MEDIUM. Ye takraav ki "probability" nahi, sirf rule-based andaaza hai.
- **Time to conflict (TTC):** kitne second mein takraav ho sakta hai. Ye sirf pakke tracks ke liye dikhta hai.
- **Faisla:** robot 100%, 50%, 25% aur 0% (ruko) speed aage simulate karke sabse tez safe option chunta hai. Zarurat ho toh object ke aane waale raaste se bachkar naya route banata hai. Har faisle ki wajah likhi aati hai, jaise *"Predicted path conflict with track 1 (person) in 2.8 s: slowing to 50%"*.
- **Reactive baseline switch:** prediction band karke purane tareeke se tulna kar sakte ho.
- **"Run predictive demo":** ek button. Robot ek aise insaan ke saamne se guzarta hai jo raasta nahi chhodta, aur chaaron steps live tick hote hain.

**Asli naapa hua nateeja** (crossing scenario, 9 alag variants, `python -m app.evaluation`):

| | Predictive | Reactive (purana) |
|---|---|---|
| Goal pahuncha | 9/9 | 7/9 |
| Takkar (collisions) | 0 | 2 |
| Bahut paas se guzarna (near miss) | 0 | 3 |
| Average time | 26.2 s | 24.9 s |

Predictive thoda dheema hai, lekin kabhi nahi takraaya. Ye nateeja ek simulated scenario ka hai; asli duniya ki safety ki guarantee nahi.

### Real-world scenarios (naya)

- 🏥 **Hospital ward:** corridor, wards (bed ke saath), reception, pharmacy, lab, ICU. Ek nurse chalti hai, aur ek visitor bina ruke raasta kaat-ta hai. Command do "Robot ko pharmacy tak le jao".
- 🏫 **University campus:** library, admin, hostel, canteen, lab block aur auditorium, ped, bench, fountain aur chalte students. Command do "Take the robot to the hostel".
- Har jagah ka naam 3D aur map dono mein likha dikhta hai.
- Har scenario ke saath ek **"Real-world use"** card hai: aise robot asli duniya mein kahan use hote hain, aur ye scenario kya fayda dikhata hai. Ye sirf intended use hai, kisi asli hospital/campus mein test nahi hua.
- Koi insaan seedha robot ki taraf aaye toh robot **side hat jaata hai** (evade), phir raasta dobara banata hai.

## 3. Safety (3 alag checks)

1. Har pal agle 4 metre ke raaste ki jaanch.
2. LiDAR aur ultrasonic sensors: 0.9 m se kam doori par robot dheere ho jaata hai, 0.3 m se kam par ruk jaata hai.
3. Physics lock: robot ko kisi cheez ke 5 cm se zyada paas nahi jaane deta.

**Emergency stop:** ek alag button jo hamesha kaam karta hai.

## 4. Sensors (sab simulated)

Camera, depth camera, 360° LiDAR, 6 ultrasonic sensors, IMU aur wheel odometry. Har sensor ki health, rate aur kitna purana data hai, ye screen par dikhta hai.

## 5. Mapping (SLAM)

- Robot LiDAR scans aur wheel odometry se **khud map banata hai**: har cell free, occupied ya unknown.
- **Scan matching** robot ki jagah ka andaaza sudhaarta hai.
  - Naapa hua farq: sirf odometry ki galti **140 cm** tak gayi, SLAM ki **8–10 cm** hi rahi.
- **Auto explore:** robot khud ghoomkar ~75–80 second (simulated time) mein warehouse ka ~90% map bana leta hai, bina takraaye.
- **Map save, load, import aur export** ROS format (PGM + YAML) mein hote hain. Tayyar demo map: `warehouse_demo`.
- **Planner kaunsa map use kare:** simulator, live SLAM map ya imported map.

## 6. Voice aur text commands

- **Bhashayein:** Hindi (देवनागरी), Hinglish aur English.
- **Kya-kya bol sakte ho:** jagah par jao, wapas start par jao, stop, pause, resume. Saath mein "safe route" aur "dheere" jaisi shartein bhi.
- **Whisper speech recognition** laptop par hi chalta hai, awaaz internet par nahi jaati. Ek command mein ~3–6 second lagte hain.
- **Fixed rules wala parser:** anjaan jagah ka andaaza nahi lagata, puchhta hai ki kaunsi jagah.
- **Confirm karne par hi** robot nayi jagah ki taraf chalta hai. Ise "Trusted mode" se band kar sakte ho.
- **Jawab usi bhasha mein** aata hai, chaho toh bolkar bhi. Text hamesha screen par rehta hai.
- **Jagahein:** Reception, Storage room, Charging dock, Loading bay, Exit, Starting point.

## 7. Accessibility (bina sune istemaal)

- Har command type karke ya list se jagah chunkar di ja sakti hai.
- Saari baatcheet ka transcript screen par rehta hai.
- Bade visual alerts icon aur text ke saath aate hain, sirf rang ya awaaz se nahi.
- **Accessible mode:** bada text, high contrast, aur alerts tab tak rehte hain jab tak tum band na karo.
- Poora flow sirf keyboard se chalaya ja sakta hai.

## 8. AI object detection

- YOLOv8n aur YOLOv8s models camera image par chalte hain.
- **Model chalane ke 3 tareeke:** single, cascade aur multi.
- **Results ka mel:** dono models ke results NMS se jode jaate hain, aur latency budget ke andar rakhe jaate hain.
- Model na ho toh simulated detector chalta hai, saaf label ke saath.

## 9. Screen par kya dikhta hai (dashboard)

- **3D warehouse:** robot, shelves, log, LiDAR dots aur raasta. Orbit, Top aur Follow camera; 2D plan view bhi.
- **Panels:**
  - Mission overview, **Prediction and risk**, Commands, Mapping, Alerts, **Evaluation**
  - Sensors, AI models, Navigation map
  - Telemetry, Event log, System health
- **Demos:**
  - **Predictive demo** (insaan raasta kaat-ta hai; robot pehle se dheema hota hai)
  - Guided demo
  - Blocked-route demo
  - "Trap the robot" game: 5 barriers se robot ko rokne ki koshish
- **Demo mode:** slow laptop ke liye halka 3D aur dheemi speed.

## 10. Website pages

Overview (problem, solution, real-world uses), Live mission, Architecture, Technology, Privacy, Terms.

## 11. Tech stack

- **Backend:** Python, FastAPI, NumPy, SciPy, OpenCV, PyTorch, Ultralytics YOLO, PyBullet, faster-whisper.
- **Frontend:** React, Vite, Three.js, Framer Motion.

## 12. Tests

- **Backend:** 155 tests pass (prediction, risk, tracking, replanning, commands, mapping aur naye scenarios samet).
- **Browser (Playwright):** 33 tests. Inme fake microphone se Whisper tak ka voice test aur predictive demo bhi hai.
- **Evaluation:** `python -m app.evaluation` (predictive vs reactive, 9+9 runs, 7 scenario checks sab pass).

## 13. Imaandari se

- Sab kuch simulated hai; koi asli robot ya sensor connected nahi hai.
- ROS 2 live SLAM is laptop par install nahi hai. README mein uska setup guide hai.
- Hindi **bolkar** command ka test nahi ho paaya, kyunki laptop mein Hindi awaaz ya recording nahi thi. Hindi **likhkar** di gayi commands tested hain.
- Sign language nahi bana hai.
- Prediction "seedhi line mein same speed" maan kar chalti hai, isliye object mudne par galti badh jaati hai (1 s ki average galti ~0.20 m). Risk level niyamon se nikalta hai, takraav ki probability nahi hai. Ye MPC nahi, ek simple speed-sampling planner hai.
- Real-world uses (hospital, warehouse, campus) sirf intended hain; kisi asli building mein test nahi hue.

Poori detail: [README.md](README.md)

*Team Hack01: Ritesh Kumar (Backend & AI/ML), Kainat Afrazi (Frontend). Hack in Hills ’26.*
