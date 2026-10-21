import pytest

from app.commands.parser import detect_language, parse
from app.commands.service import CommandService
from app.simulation.scenarios import SCENARIOS
from conftest import run_until

PLACES = SCENARIOS["warehouse"].places


@pytest.mark.parametrize(
    "text, intent, dest, lang",
    [
        ("Robot ko reception tak le jao.", "navigate", "reception", "hi-Latn"),
        ("Take the robot to the storage room.", "navigate", "storage", "en"),
        ("Find a safe route to the exit.", "navigate", "exit", "en"),
        ("Stop.", "stop", None, "en"),
        ("Pause navigation.", "pause", None, "en"),
        ("Resume.", "resume", None, "en"),
        ("Return to the starting point.", "return_home", "start", "en"),
        ("रोबोट को रिसेप्शन तक ले जाओ", "navigate", "reception", "hi"),
        ("रुको", "stop", None, "hi"),
        ("थोड़ा रुको", "pause", None, "hi"),
        ("फिर से चलो", "resume", None, "hi"),
        ("वापस जाओ", "return_home", "start", "hi"),
        ("चार्जिंग डॉक पर जाओ", "navigate", "charging", "hi"),
        ("dheere dheere loading bay chalo", "navigate", "loading", "hi-Latn"),
    ],
)
def test_parser_examples(text, intent, dest, lang):
    c = parse(text, PLACES)
    assert c.intent == intent
    assert (c.destination or {}).get("key") == dest
    assert c.language == lang


def test_stop_wins_over_everything():
    c = parse("go to the reception, no wait, stop!", PLACES)
    assert c.intent == "stop"


def test_constraints():
    assert parse("Find a safe route to the exit", PLACES).constraints == {"careful": True}
    assert parse("गोदाम तक धीरे चलो", PLACES).constraints == {"slow": True}


def test_unknown_ambiguous_and_nonsense_are_never_guessed():
    c = parse("Take me to the cafeteria", PLACES)
    assert c.issue == "unknown_destination" and c.destination is None
    c = parse("reception se exit tak jao", PLACES)
    assert c.issue == "ambiguous" and set(c.candidates) == {"Reception", "Exit"}
    assert parse("hello there", PLACES).issue == "not_understood"
    assert parse("   ", PLACES).issue == "empty"


def test_coordinates():
    c = parse("go to 12, 6", PLACES)
    assert c.destination == {"x": 12.0, "y": 6.0}


def test_language_detection():
    assert detect_language("रुको") == "hi"
    assert detect_language("robot ko exit tak le jao") == "hi-Latn"
    assert detect_language("take the robot to the exit") == "en"


# ------------------------------------------------------------ service
@pytest.fixture
def svc(engine):
    engine.params["moving_obstacles"] = False
    return CommandService(engine)


def test_navigation_waits_for_confirmation_then_runs(svc, engine):
    rec = svc.interpret("Robot ko reception tak le jao", "text")
    assert rec["status"] == "awaiting_confirmation"
    assert rec["validation"]["valid"] and rec["validation"]["reachable"]
    assert "Confirm" in rec["response"]["text"] and rec["response"]["language"] == "hi-Latn"
    assert engine.status == "idle"  # nothing moved yet
    rec = svc.confirm(rec["id"])
    assert rec["status"] == "executed"
    assert engine.target == (2.0, 10.5)
    assert run_until(engine, {"goal_reached"}, max_seconds=60)


def test_trusted_mode_executes_and_stop_is_immediate(svc, engine):
    rec = svc.interpret("Take the robot to the exit", "text", trusted=True)
    assert rec["status"] == "executed"
    run_until(engine, {"navigating"})
    rec = svc.interpret("रुको", "speech")
    assert rec["status"] == "executed" and engine.status == "stopped"
    assert rec["response"]["text"].startswith("रुक गया")


def test_hindi_response_and_cancel(svc, engine):
    rec = svc.interpret("गोदाम तक ले चलो")
    assert rec["status"] == "awaiting_confirmation"
    assert "स्टोर रूम" in rec["response"]["text"]
    assert svc.cancel(rec["id"])["status"] == "cancelled"
    assert engine.target is None


def test_unreachable_destination_is_explained(engine):
    engine.reset("enclosed")
    svc = CommandService(engine)
    rec = svc.interpret("go to the inner bay", trusted=True)
    # Known place, but no route: never executed automatically, even in trusted mode.
    assert rec["status"] == "awaiting_confirmation"
    assert rec["validation"]["reachable"] is False
    assert "Blocked" in rec["response"]["text"]
    svc.confirm(rec["id"])
    assert run_until(engine, {"blocked", "blocked_waiting"}, max_seconds=5)
    assert engine.distance_travelled == 0.0


def test_unknown_place_asks_for_clarification(svc):
    rec = svc.interpret("take the robot to the cafeteria")
    assert rec["status"] == "needs_clarification"
    assert "Reception" in rec["response"]["text"]


def test_careful_constraint_applies_and_is_restored(svc, engine):
    before = dict(engine.params)
    svc.interpret("Find a safe route to the exit", trusted=True)
    assert engine.params["safety_margin"] == 0.30 and engine.params["max_speed"] <= 0.6
    svc.interpret("stop")
    assert engine.params["safety_margin"] == before["safety_margin"]
    assert engine.params["max_speed"] == before["max_speed"]


def test_pause_without_mission_is_rejected(svc):
    rec = svc.interpret("Pause navigation")
    assert rec["status"] == "rejected" and "no mission" in rec["response"]["text"]
