"""Deterministic demonstration scenarios. Each call returns a fresh World."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from .world import Obstacle, RobotState, World

MAP_W, MAP_H = 20.0, 12.0


def _rect(id_, label, x, y, w, h, height=1.8):
    return Obstacle(id=id_, label=label, shape="rect", x=x, y=y, w=w, h=h, height=height)


def _warehouse() -> World:
    obstacles = [
        _rect("shelf-1", "shelf", 5.0, 9.75, 1.0, 3.5),
        _rect("shelf-2", "shelf", 5.0, 2.25, 1.0, 3.5),
        _rect("shelf-3", "shelf", 10.0, 8.0, 6.0, 1.0),
        _rect("shelf-4", "shelf", 10.0, 4.0, 6.0, 1.0),
        _rect("shelf-5", "shelf", 15.0, 10.0, 1.0, 3.0),
        _rect("shelf-6", "shelf", 15.0, 2.0, 1.0, 3.0),
        _rect("pallet-1", "pallet", 8.5, 10.5, 1.2, 1.0, height=0.6),
        _rect("pallet-2", "pallet", 12.0, 1.6, 1.2, 1.0, height=0.6),
        Obstacle(
            id="person-1",
            label="person",
            shape="circle",
            x=17.0,
            y=2.0,
            r=0.3,
            height=1.75,
            dynamic=True,
            patrol=[(17.0, 2.0), (17.0, 10.0)],
            speed=0.45,
        ),
    ]
    robot = RobotState(x=1.5, y=6.0, theta=0.0)
    return World(MAP_W, MAP_H, robot, obstacles)


def _slalom() -> World:
    obstacles = [
        _rect("wall-1", "barrier", 5.0, 4.0, 0.6, 8.0),
        _rect("wall-2", "barrier", 10.0, 8.0, 0.6, 8.0),
        _rect("wall-3", "barrier", 15.0, 4.0, 0.6, 8.0),
        Obstacle(id="cone-1", label="cone", shape="circle", x=7.5, y=9.0, r=0.4, height=0.7),
        Obstacle(id="cone-2", label="cone", shape="circle", x=12.5, y=3.0, r=0.4, height=0.7),
    ]
    robot = RobotState(x=1.5, y=2.0, theta=math.pi / 2)
    return World(MAP_W, MAP_H, robot, obstacles)


def _enclosed() -> World:
    # The target bay is fully enclosed, so no collision-free route exists.
    obstacles = [
        _rect("bay-n", "barrier", 16.0, 8.5, 5.0, 0.6),
        _rect("bay-s", "barrier", 16.0, 3.5, 5.0, 0.6),
        _rect("bay-w", "barrier", 13.8, 6.0, 0.6, 5.6),
        _rect("bay-e", "barrier", 18.2, 6.0, 0.6, 5.6),
        _rect("shelf-1", "shelf", 7.0, 9.0, 1.0, 4.0),
        _rect("shelf-2", "shelf", 7.0, 3.0, 1.0, 4.0),
    ]
    robot = RobotState(x=1.5, y=6.0, theta=0.0)
    return World(MAP_W, MAP_H, robot, obstacles)


def _crossing() -> World:
    # A corridor between two walls with doorways at x = 10. A person who does not give
    # way crosses the corridor through the doorways (and disappears behind the walls,
    # so its track is lost and re-acquired); a cart drives a rectangular loop, changing
    # direction at each corner and crossing the route twice; a crate stands on the
    # direct route.
    obstacles = [
        _rect("wall-nw", "barrier", 4.75, 9.15, 9.5, 0.3, height=2.0),
        _rect("wall-ne", "barrier", 15.25, 9.15, 9.5, 0.3, height=2.0),
        _rect("wall-sw", "barrier", 4.75, 2.85, 9.5, 0.3, height=2.0),
        _rect("wall-se", "barrier", 15.25, 2.85, 9.5, 0.3, height=2.0),
        _rect("crate-1", "crate", 4.5, 6.0, 0.8, 0.8, height=1.0),
        Obstacle(id="person-1", label="person", shape="circle", x=10.0, y=11.5, r=0.3, height=1.75, dynamic=True,
                 patrol=[(10.0, 11.5), (10.0, 0.5)], speed=0.6, yields=False),
        Obstacle(id="cart-1", label="cart", shape="rect", x=14.0, y=8.4, w=0.7, h=0.7, height=1.0, dynamic=True,
                 patrol=[(14.0, 8.4), (14.0, 3.6), (17.5, 3.6), (17.5, 8.4)], speed=0.5, yields=False),
    ]
    robot = RobotState(x=1.5, y=6.0, theta=0.0)
    return World(MAP_W, MAP_H, robot, obstacles)


def _wall_with_doors(prefix, y, doors, t=0.2, door=1.6, height=2.4):
    """Horizontal wall across the map at ``y`` with door openings centred on ``doors``."""
    edges = [0.0]
    for d in doors:
        edges += [d - door / 2, d + door / 2]
    edges.append(MAP_W)
    out = []
    for i in range(0, len(edges), 2):
        x0, x1 = edges[i], edges[i + 1]
        out.append(_rect(f"{prefix}-{i // 2 + 1}", "wall", (x0 + x1) / 2, y, x1 - x0, t, height=height))
    return out


def _hospital() -> World:
    # A hospital ward floor: a 3 m corridor with rooms on both sides (door openings at
    # x = 4, 10, 16). A nurse walks the corridor and gives way; a visitor crosses from
    # Ward A to the Lab without giving way.
    obstacles = [
        *_wall_with_doors("wall-n", 7.6, (4.0, 10.0, 16.0)),
        *_wall_with_doors("wall-s", 4.4, (4.0, 10.0, 16.0)),
        # Automatic sliding doors in every doorway (they open for the robot and for people).
        *[_rect(f"door-{side}{i + 1}", "door", x, y, 1.6, 0.08, height=2.1)
          for side, y in (("n", 7.6), ("s", 4.4)) for i, x in enumerate((4.0, 10.0, 16.0))],
        _rect("div-n1", "wall", 7.0, 9.85, 0.2, 4.3, height=2.4),
        _rect("div-n2", "wall", 13.0, 9.85, 0.2, 4.3, height=2.4),
        _rect("div-s1", "wall", 7.0, 2.15, 0.2, 4.3, height=2.4),
        _rect("div-s2", "wall", 13.0, 2.15, 0.2, 4.3, height=2.4),
        _rect("reception-desk", "counter", 3.5, 10.6, 3.0, 0.6, height=1.05),
        _rect("bed-a1", "bed", 8.6, 10.8, 1.0, 2.0, height=0.7),
        _rect("bed-a2", "bed", 11.4, 10.8, 1.0, 2.0, height=0.7),
        _rect("bed-b1", "bed", 14.6, 10.8, 1.0, 2.0, height=0.7),
        _rect("bed-b2", "bed", 18.4, 10.8, 1.0, 2.0, height=0.7),
        _rect("pharmacy-counter", "counter", 3.5, 1.0, 4.0, 0.6, height=1.05),
        _rect("lab-bench", "counter", 10.0, 1.0, 4.0, 0.6, height=0.95),
        _rect("icu-bed", "bed", 16.5, 1.4, 2.0, 1.0, height=0.7),
        _rect("trolley-1", "trolley", 12.6, 7.05, 0.8, 0.5, height=1.0),
        Obstacle(id="planter-1", label="planter", shape="circle", x=19.4, y=7.0, r=0.25, height=1.1),
        Obstacle(id="nurse-1", label="person", shape="circle", x=6.0, y=5.3, r=0.3, height=1.7, dynamic=True,
                 patrol=[(6.0, 5.3), (14.0, 5.3)], speed=0.6),
        Obstacle(id="visitor-1", label="person", shape="circle", x=10.0, y=9.6, r=0.3, height=1.75, dynamic=True,
                 patrol=[(10.0, 9.6), (10.0, 2.4)], speed=0.7, yields=False),
    ]
    robot = RobotState(x=1.5, y=6.0, theta=0.0)
    return World(MAP_W, MAP_H, robot, obstacles)


def _campus() -> World:
    # An outdoor university plaza between six buildings, with trees, benches and a
    # central fountain. Students walk along the plaza; one crosses it without giving way.
    obstacles = [
        _rect("library", "building", 3.0, 10.0, 5.0, 3.4, height=5.0),
        _rect("admin-block", "building", 10.0, 10.4, 4.0, 2.6, height=4.2),
        _rect("hostel", "building", 17.0, 10.0, 5.0, 3.4, height=5.6),
        _rect("canteen", "building", 3.0, 2.0, 5.0, 3.2, height=3.6),
        _rect("lab-block", "building", 10.5, 1.6, 4.0, 2.4, height=4.6),
        _rect("auditorium", "building", 17.0, 2.0, 5.0, 3.2, height=5.0),
        Obstacle(id="fountain", label="fountain", shape="circle", x=10.0, y=6.0, r=0.8, height=0.9),
        Obstacle(id="tree-1", label="tree", shape="circle", x=6.8, y=7.6, r=0.45, height=3.2),
        Obstacle(id="tree-2", label="tree", shape="circle", x=13.2, y=7.6, r=0.45, height=3.4),
        Obstacle(id="tree-3", label="tree", shape="circle", x=6.8, y=4.4, r=0.45, height=3.0),
        Obstacle(id="tree-4", label="tree", shape="circle", x=13.2, y=4.4, r=0.45, height=3.3),
        _rect("bench-1", "bench", 10.0, 7.7, 1.2, 0.4, height=0.5),
        _rect("bench-2", "bench", 8.4, 4.4, 1.2, 0.4, height=0.5),
        Obstacle(id="student-1", label="person", shape="circle", x=2.0, y=7.0, r=0.3, height=1.7, dynamic=True,
                 patrol=[(2.0, 7.0), (18.5, 7.0)], speed=0.8),
        Obstacle(id="student-2", label="person", shape="circle", x=15.0, y=8.0, r=0.3, height=1.75, dynamic=True,
                 patrol=[(15.0, 8.0), (15.0, 4.0)], speed=0.9, yields=False),
    ]
    robot = RobotState(x=1.2, y=5.6, theta=0.0)
    return World(MAP_W, MAP_H, robot, obstacles)


@dataclass(frozen=True)
class Place:
    """A named destination users can ask for by voice or text. ``aliases`` are matched
    by the command parser (English, romanised Hindi and Devanagari)."""

    key: str
    name: str
    name_hi: str
    x: float
    y: float
    aliases: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"key": self.key, "name": self.name, "name_hi": self.name_hi, "x": self.x, "y": self.y,
                "aliases": list(self.aliases)}


START_ALIASES = ("start", "starting point", "start point", "home", "base", "shuruaat", "shuruat", "शुरुआत",
                 "शुरूआत", "शुरुआती जगह", "होम")


@dataclass(frozen=True)
class Zone:
    """A speed-limited area (quiet ward, pedestrian plaza, loading dock)."""

    key: str
    name: str
    x0: float
    y0: float
    x1: float
    y1: float
    max_speed: float  # m/s
    kind: str = "quiet"

    def contains(self, x: float, y: float) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    def to_dict(self) -> dict:
        return {"key": self.key, "name": self.name, "x0": self.x0, "y0": self.y0, "x1": self.x1, "y1": self.y1,
                "max_speed": self.max_speed, "kind": self.kind}


DOCK_ALIASES = ("charging dock", "charging", "charger", "dock", "चार्जिंग", "चार्जर", "डॉक")


@dataclass(frozen=True)
class Scenario:
    key: str
    name: str
    description: str
    default_target: tuple[float, float]
    build: Callable[[], World]
    places: tuple[Place, ...] = field(default_factory=tuple)
    zones: tuple[Zone, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "default_target": {"x": self.default_target[0], "y": self.default_target[1]},
            "places": [p.to_dict() for p in self.places],
            "zones": [z.to_dict() for z in self.zones],
        }


SCENARIOS: dict[str, Scenario] = {
    s.key: s
    for s in [
        Scenario(
            "warehouse",
            "Warehouse aisle",
            "Shelving aisles with a patrolling person. Used for the guided demo.",
            (18.5, 6.0),
            _warehouse,
            (
                Place("start", "Starting point", "शुरुआत", 1.5, 6.0, START_ALIASES),
                Place("reception", "Reception", "रिसेप्शन", 2.0, 10.5,
                      ("reception", "front desk", "help desk", "swagat kaksh", "रिसेप्शन", "स्वागत कक्ष")),
                Place("storage", "Storage room", "स्टोर रूम", 11.5, 10.3,
                      ("storage room", "storage", "store room", "storeroom", "godown", "bhandar",
                       "स्टोर रूम", "स्टोरेज", "गोदाम", "भंडार")),
                Place("charging", "Charging dock", "चार्जिंग डॉक", 1.2, 1.2,
                      ("charging dock", "charging", "charger", "चार्जिंग", "चार्जर")),
                Place("loading", "Loading bay", "लोडिंग बे", 18.5, 10.5,
                      ("loading bay", "loading dock", "loading", "लोडिंग")),
                Place("exit", "Exit", "निकास", 18.5, 6.0,
                      ("exit", "way out", "bahar", "nikas", "nikaas", "निकास", "बाहर", "एग्जिट", "एक्जिट")),
            ),
            (Zone("dock", "Loading dock: slow", 16.0, 9.0, 20.0, 12.0, 0.5, "slow"),),
        ),
        Scenario(
            "crossing",
            "Predictive crossing",
            "A person who does not give way crosses the robot's corridor, a cart changes direction, a crate blocks the direct line.",
            (18.5, 6.0),
            _crossing,
            (
                Place("start", "Starting point", "शुरुआत", 1.5, 6.0, START_ALIASES),
                Place("exit", "Exit", "निकास", 18.5, 6.0,
                      ("exit", "way out", "bahar", "nikas", "nikaas", "निकास", "बाहर", "एग्जिट", "एक्जिट")),
                Place("midpoint", "Corridor midpoint", "गलियारे का बीच", 12.0, 6.0,
                      ("midpoint", "middle", "corridor", "beech", "गलियारा", "बीच")),
                Place("charging", "Charging dock", "चार्जिंग डॉक", 1.2, 4.0, DOCK_ALIASES),
            ),
        ),
        Scenario(
            "hospital",
            "Hospital ward",
            "A ward corridor with rooms on both sides: deliver medicines between reception, wards, pharmacy, lab and ICU while a nurse and a visitor walk the corridor.",
            (16.0, 2.9),
            _hospital,
            (
                Place("start", "Corridor entrance", "गलियारे का प्रवेश", 1.5, 6.0, START_ALIASES + ("entrance", "प्रवेश")),
                Place("reception", "Reception", "रिसेप्शन", 4.0, 9.3,
                      ("reception", "front desk", "help desk", "swagat kaksh", "रिसेप्शन", "स्वागत कक्ष")),
                Place("ward_a", "Ward A", "वार्ड ए", 9.0, 9.0, ("ward a", "ward 1", "वार्ड ए", "वार्ड 1")),
                Place("ward_b", "Ward B", "वार्ड बी", 16.0, 9.2, ("ward b", "ward 2", "वार्ड बी", "वार्ड 2")),
                Place("pharmacy", "Pharmacy", "फार्मेसी", 4.0, 2.6,
                      ("pharmacy", "medicine store", "dawai", "dawakhana", "फार्मेसी", "दवाखाना", "दवाई")),
                Place("lab", "Lab", "लैब", 11.0, 2.6, ("lab", "laboratory", "pathology", "लैब", "प्रयोगशाला")),
                Place("icu", "ICU", "आईसीयू", 16.0, 2.9, ("icu", "intensive care", "आईसीयू")),
                Place("exit", "Exit", "निकास", 19.0, 6.0,
                      ("exit", "way out", "bahar", "nikas", "nikaas", "निकास", "बाहर", "एग्जिट")),
                Place("charging", "Charging dock", "चार्जिंग डॉक", 1.0, 3.3, DOCK_ALIASES),
            ),
            (
                Zone("wards", "Quiet zone: wards", 7.1, 7.7, 20.0, 12.0, 0.4),
                Zone("icu", "Quiet zone: ICU", 13.1, 0.0, 20.0, 4.3, 0.35),
            ),
        ),
        Scenario(
            "campus",
            "University campus",
            "An outdoor plaza between six campus buildings: deliver parcels and food between the gate, library, canteen, hostel and labs around students and a fountain.",
            (17.0, 7.5),
            _campus,
            (
                Place("start", "Main gate", "मुख्य द्वार", 1.2, 5.6, START_ALIASES + ("gate", "main gate", "मुख्य द्वार", "गेट")),
                Place("library", "Library", "पुस्तकालय", 3.0, 7.3, ("library", "pustakalay", "पुस्तकालय", "लाइब्रेरी")),
                Place("admin", "Admin block", "प्रशासन भवन", 10.0, 8.4, ("admin block", "admin", "office", "प्रशासन", "एडमिन")),
                Place("hostel", "Hostel", "छात्रावास", 17.0, 7.5, ("hostel", "chhatravas", "छात्रावास", "हॉस्टल")),
                Place("canteen", "Canteen", "कैंटीन", 3.0, 4.7, ("canteen", "cafeteria", "mess", "कैंटीन", "कैफेटेरिया")),
                Place("lab_block", "Lab block", "प्रयोगशाला भवन", 10.5, 3.6, ("lab block", "labs", "lab", "प्रयोगशाला", "लैब")),
                Place("auditorium", "Auditorium", "सभागार", 17.0, 4.6, ("auditorium", "hall", "सभागार", "ऑडिटोरियम")),
                Place("charging", "Charging dock", "चार्जिंग डॉक", 1.2, 4.4, DOCK_ALIASES),
            ),
            (Zone("plaza", "Pedestrian plaza", 7.5, 4.0, 12.5, 8.0, 0.5, "pedestrian"),),
        ),
        Scenario(
            "slalom",
            "Slalom barriers",
            "Staggered barriers that force a long, winding route.",
            (18.5, 10.0),
            _slalom,
            (
                Place("start", "Starting point", "शुरुआत", 1.5, 2.0, START_ALIASES),
                Place("finish", "Finish", "फिनिश", 18.5, 10.0, ("finish", "finish line", "end", "फिनिश", "अंत")),
            ),
        ),
        Scenario(
            "enclosed",
            "Enclosed bay (unreachable)",
            "The target sits inside a sealed bay. The planner must report Blocked.",
            (16.0, 6.0),
            _enclosed,
            (
                Place("start", "Starting point", "शुरुआत", 1.5, 6.0, START_ALIASES),
                Place("bay", "Inner bay", "अंदर का बे", 16.0, 6.0,
                      ("inner bay", "bay", "sealed bay", "andar ka bay", "अंदर का बे", "बे")),
            ),
        ),
    ]
}

DEFAULT_SCENARIO = "warehouse"
