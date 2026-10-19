# Deck content inventory

Source: `Hack01_Hack in Hills ’26.pptx` (8 slides, read in full including embedded diagrams). All copy lives in `frontend/src/content/deck.js`.

| Slide | Content | Website location | Notes |
|---|---|---|---|
| 1 Team | Team Hack01; Ritesh Kumar (Backend & AI/ML), Kainat Afrazi (Frontend) | Overview → *Who built it*; footer; README | Event/sponsor logos and the mountain photo were not reused (third-party branding). |
| 2 Problem & theme | Problem statement, 5-point challenge, theme alignment | Overview → *The problem* | Added an expandable “why perception matters” explanation. |
| 3 Solution | Summary, 7-step overview, 6 key features, unique value | Overview → *The solution*, features table with implementation status | Each feature labelled implemented / simulation / fallback. |
| 4 Architecture: tech stack | Frontend, backend, CV, AI, navigation, WebSocket, PyBullet | Technology page (deck vs. actually used) | Lucide React replaced by inline SVG (design brief); noted in table. |
| 4 Architecture: data flow | Camera → OpenCV → YOLO → scene → target → decision → A* → avoidance → controller → movement → feedback (loop) | Architecture → *Data flow* | |
| 4 Architecture: APIs | REST, `/ws/telemetry`, YOLO interface, PyBullet API | Architecture → *APIs and interfaces*; docs/API.md | PyBullet used for rendering/collision, not motor commands: marked partial. |
| 4 Architecture diagram (image) | 3 layers, 11 stages, continuous replanning | Architecture → interactive explorer (+ original image) | “A* / Dijkstra”: only A* implemented, stated. OpenCV preprocessing marked partial. |
| 5 Market research | 4×4 qualitative table | Overview → *Where it applies* | Labelled qualitative, unverified. |
| 6 Mission | Mission line + 7-step process diagram (with yes/no branch) | Overview hero + interactive *How a mission runs* (+ original image); guided demo | |
| 7 Future scope | 4 phases, 16 items, journey line | Future scope page; Overview strip | Phase 1 items labelled by actual status; phases 2–4 future scope. |
| 8 Thank you | — | Not used | |
