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
class Scenario:
    key: str
    name: str
    description: str
    default_target: tuple[float, float]
    build: Callable[[], World]
    places: tuple[Place, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "default_target": {"x": self.default_target[0], "y": self.default_target[1]},
            "places": [p.to_dict() for p in self.places],
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
