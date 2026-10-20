# VISTARA-X: Simple Bhasha Mein

**Ek line mein:** VISTARA-X ek robot hai jo computer ke andar bane ek warehouse (simulation) mein chalta hai. Ye apne aas-paas dekhta hai, target tak safe raasta dhoondta hai, raasta block ho jaaye toh ruk jaata hai, aur naya raasta bana leta hai.

---

## 1. Idea kya hai

### Problem

Socho ek delivery robot hai jo warehouse mein point A se point B tak jaata hai. Raaste mein:

- shelves aur pallets hain jo kabhi hilte nahi,
- boxes hain jo koi bhi achaanak raaste mein rakh sakta hai,
- log hain jo idhar-udhar chal rahe hain.

Robot ko target tak **bina kisi cheez se takraaye** pahunchna hai. Aur agar sach mein koi raasta hi nahi hai, toh use **imaandari se bolna** chahiye ki "raasta nahi hai". Na crash kare, na jhooth-mooth ki koshish ka dikhawa kare.

### Humara solution

Humne robot ka "dimaag" banaya aur use asli hardware ki jagah ek realistic simulation mein test kiya. Robot ek simple loop baar-baar chalata hai, ek second mein kai baar:

```
Dekho  →  Samjho  →  Raasta plan karo  →  Chalo  →  Check karte raho  →  Block hua toh naya raasta
```

Bilkul waise hi jaise tum bheed waale kamre mein chalte ho. Pehle dekhte ho, raasta chunte ho, chalna shuru karte ho. Koi saamne aa jaaye toh rukte ho aur doosra raasta le lete ho.

---

## 2. Ye kaam kaise karta hai (step by step)

| Step | Robot kya karta hai | Real life mein jaise |
|---|---|---|
| 1. Dekhna | Sensors padhta hai: camera, depth camera, LiDAR (laser se doori naapne waala scanner), ultrasonic sensors, IMU (ghoomne ka sensor) aur wheel counters | Tumhari aankhein aur balance |
| 2. Pehchaanna | YOLO AI model camera ki image dekh kar batata hai ki saamne kya hai (jaise "person") | Saamne khade insaan ko pehchaan lena |
| 3. Samajhna | Floor ka map banata hai: 20 cm ke chhote-chhote squares ka grid, har square ya toh free hai ya blocked. Blocked squares ke around ek extra safety border bhi lagta hai | Ye pata hona ki furniture kahan rakha hai |
| 4. Plan karna | **A\*** (A-star) algorithm grid par sabse chhota safe raasta dhoondta hai. Use karne se pehle raasta dobara check hota hai | Google Maps ka route dhoondna |
| 5. Chalna | Controller robot ko raaste par smoothly chalata hai | Raaste par chalna |
| 6. Check aur re-plan | Har pal agle 4 metre check karta hai. Kuch raasta block kare toh robot **ruk jaata hai**, 0.3 second rukta hai, naya raasta banata hai, check karta hai, phir chalta hai | Koi saamne aa jaaye toh side se nikal jaana |

### Safety: teen alag-alag checks

Robot tabhi chalta rehta hai jab teeno checks bolein ki sab safe hai:

1. **Raasta check:** kya plan kiya hua raasta map par abhi bhi khaali hai?
2. **Doori waale sensors:** LiDAR aur ultrasonic naapte hain ki cheezein kitni paas hain. 0.9 m se kam doori par robot dheere ho jaata hai, 0.3 m se kam par ruk jaata hai.
3. **Final safety lock:** physics check aisi koi bhi movement rok deta hai jisse robot kisi cheez ke 5 cm se zyada paas aa jaaye.

Agar koi bhi safe raasta nahi hai, toh robot **Blocked** dikhata hai aur apni jagah se hilta nahi.

---

## 3. Ye bana kaise hai

Project ke do hisse hain jo aapas mein baat karte hain:

```
┌──────────────────────────────────┐     live updates (1 second mein 10 baar)   ┌──────────────────────────────┐
│  backend/  (Python)              │  ────────────────────────────────────────▶ │  frontend/  (website)        │
│  robot ka dimaag + warehouse     │  ◀──────────────────────────────────────── │  3D view + control panel     │
└──────────────────────────────────┘     commands (start, stop, ...)            └──────────────────────────────┘
```

### Backend (dimaag), `backend/` folder mein

| Hissa | Kya karta hai | Kahan hai |
|---|---|---|
| Simulation | Virtual warehouse ko 1 second mein 20 baar update karta hai: robot, shelves, boxes, log | `app/simulation/` |
| Path planning | Grid map par A\* search | `app/navigation/` |
| Steering | Robot ko raaste par chalata hai | `app/control/` |
| Sensors | Simulated camera, LiDAR, ultrasonic, IMU, wheel counters (asli jaisa thoda noise bhi) | `app/sensors/` |
| AI detection | YOLOv8 models jo camera image mein cheezein pehchaante hain | `app/perception/` |
| Physics | PyBullet takkar check karta hai aur camera ki image banata hai | `app/simulation/physics.py` |
| API | Website se commands leta hai aur live data bhejta hai | `app/api/` |

Isme use hua: **Python, FastAPI, OpenCV, NumPy, PyTorch, Ultralytics YOLO, PyBullet**.

### Frontend (screen), `frontend/` folder mein

| Hissa | Kya dikhata hai |
|---|---|
| 3D view | Warehouse, robot, uska raasta, LiDAR ke dots aur log, sab 3D mein (2D flat map bhi hai) |
| Mission controls | Target chuno, Start, Pause, Stop, obstacles ya log add karo |
| Panels | Sensors, AI detection, navigation map, live numbers, event log, system health |
| Demos | Ek click waala guided demo aur blocked-route demo |
| Challenge | "Trap the robot" game: 5 barriers se robot ko rokne ki koshish karo |

Isme use hua: **React, Vite, Three.js (3D), Framer Motion (animations)**.

---

## 4. Use kaise karein

### Chalana kaise hai (Windows)

**Terminal 1, backend:**

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-optional.txt
python -m uvicorn app.main:app --port 8000
```

**Terminal 2, website:**

```bash
cd frontend
npm install
npm run dev
```

Browser mein **http://localhost:5173** kholo aur **Live mission** par click karo.

### Try karke dekho

1. **Laptop slow hai?** Upar **Demo mode** tick karo. 3D view halka ho jaata hai aur robot dheere chalta hai, toh follow karna aasaan hai.
2. **Target chuno:** **Select destination** dabao aur floor par kahin bhi click karo, ya `18.5` aur `6` type karo.
3. **Start karo:** **Start mission** dabao. Raasta dikhega aur robot chalne lagega.
4. **Raasta block karo:** robot jab shuruaat mein hi ho, tab **Drop obstacle on route** dabao. Robot rukega, **Replanning** dikhayega, aur obstacle ke around se nikal jaayega.
5. **Finish:** robot target tak pahunch jaata hai. Collision count 0 hi rehta hai.
6. **Impossible case:** **Run blocked-route demo** dabao. Target chaaron taraf deewaron se band hai, toh robot **Blocked** dikhata hai aur hilta nahi.
7. **Game khelo: "Trap the robot"** panel mein **Start challenge** dabao. Tumhare paas 5 barriers hain. Robot chal raha hota hai aur tumhe floor par click karke uska raasta rokna hai. Thoda bhi gap chhoda toh robot naya raasta dhoondh kar nikal jaayega (robot jeeta). Poora band kar diya toh robot imaandari se **Blocked** bolega (tum jeete). Dono case mein collisions 0 hi rehte hain. Hint: x = 15 par dono racks ke beech ka gap dekho. Judges ko mouse pakdao, ye sabse interactive part hai.
8. **Khelo:** boxes ya chalta hua insaan add karo, LiDAR band karo, YOLO AI model chuno, ya camera view badlo (Orbit, Top, Follow robot).

Time kam hai? **Run guided demo** dabao, ye steps 2 se 5 khud kar deta hai.

### Real duniya mein iska kya use hai

- **Warehouses aur factories:** shelves ke beech saamaan dhone waale robots.
- **Hospitals:** bheed waale corridors mein dawaai pahunchane waale robots.
- **Delivery aur cleaning robots:** logon ke beech safely chalna.
- **Banane se pehle testing:** mehenga hardware khareedne se pehle robot ka dimaag simulation mein test kar sakte hain.

---

## 5. Imaandari se kuch baatein

- Abhi sab kuch **simulated** hai. Koi asli robot ya sensor connected nahi hai.
- AI models aam photos (COCO dataset) par trained hain, isliye humare computer se bane warehouse mein kam cheezein pehchaante hain.
- Humne automated tests chalaye hain (92 backend, 26 browser), lekin bahut saare runs par accuracy ya success rate abhi naapa nahi hai.

Poori technical detail ke liye [README.md](README.md) dekho.

*Team Hack01: Ritesh Kumar (Backend & AI/ML), Kainat Afrazi (Frontend). Hack in Hills ’26.*
