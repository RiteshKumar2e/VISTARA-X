import pytest

from app.commands.parser import parse
from app.simulation.scenarios import SCENARIOS
from conftest import run_until


@pytest.mark.parametrize("key", ["warehouse", "crossing", "hospital", "campus"])
def test_every_named_place_is_valid_and_reachable(engine, key):
    engine.reset(key)
    for p in SCENARIOS[key].places:
        check = engine.preview_route(p.x, p.y)
        assert check["valid"], (key, p.key, check["message"])
        assert check["reachable"], (key, p.key)


@pytest.mark.parametrize("key,place", [("hospital", "icu"), ("campus", "hostel")])
def test_real_world_missions_reach_the_goal_without_collisions(engine, key, place):
    engine.reset(key)
    p = next(pl for pl in SCENARIOS[key].places if pl.key == place)
    engine.set_target(p.x, p.y)
    engine.navigate()
    assert run_until(engine, {"goal_reached"}, max_seconds=120)
    assert engine.collisions == 0


def test_hindi_commands_find_the_new_places():
    hosp = SCENARIOS["hospital"].places
    camp = SCENARIOS["campus"].places
    assert parse("रोबोट को फार्मेसी तक ले जाओ", hosp).destination["key"] == "pharmacy"
    assert parse("take the robot to the icu", hosp).destination["key"] == "icu"
    assert parse("robot ko library tak le jao", camp).destination["key"] == "library"
    assert parse("हॉस्टल तक ले चलो", camp).destination["key"] == "hostel"
    # "ward" alone names two wards: ask, never guess.
    assert parse("go to the ward", hosp).issue in ("ambiguous", "unknown_destination")
