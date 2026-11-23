"""
The analysis on real detections: the CAVIAR clip TwoEnterShop2cor (a mall corridor, 64 s), tracked with the real
pipeline, with the marks a user drew and the entries the CAVIAR hand labels give. It keeps the door logic honest
against real people, who stop short of a door, walk along it and vanish behind it, in a way a simulated walker does not.
"""

import json
from pathlib import Path

import pytest

import places

DATA = Path(__file__).parent / "data" / "caviar_two_enter_shop.json"


@pytest.fixture(scope="module")
def clip():
    d = json.loads(DATA.read_text(encoding="utf-8"))
    d["tracks"] = {int(t): [tuple(o) for o in obs] for t, obs in d["tracks"].items()}
    d["person_of"] = {int(t): p for t, p in d["person_of"].items()}
    return d


@pytest.fixture(scope="module")
def result(clip):
    return places.analyze(clip["tracks"], clip["person_of"], clip["places"], clip["width"], clip["height"],
                          clip["fps"], clip["last_fid"])


def test_every_entry_reported_is_one_the_labels_have(clip, result):
    enters = [e["time_s"] for e in result["events"] if e["event"] == "enter"]
    assert enters, "the people who walk into the shop must be found"
    assert all(any(abs(t - g) <= 1.0 for g in clip["gt_enter_s"]) for t in enters), enters


def test_most_of_the_labelled_entries_are_found(clip, result):
    enters = [e["time_s"] for e in result["events"] if e["event"] == "enter"]
    found = sum(any(abs(t - g) <= 1.0 for t in enters) for g in clip["gt_enter_s"])
    assert found >= 4, (found, enters)       # one of the five is the second of two people walking in together


def test_a_person_standing_at_the_next_door_is_not_given_to_this_one(result):
    # the person at the first shop's door at about 40 s used to be credited with an exit from the second shop
    assert not any(e["place"] == "Shop 2" and 40 <= e["time_s"] <= 41 for e in result["events"])
