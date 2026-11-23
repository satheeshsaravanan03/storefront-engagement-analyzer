"""Tests for journeys.py: per-shop numbers, overlaps between shops and the order people went through them."""

import pytest

import journeys

PLACES = [
    {"name": "A", "front": [[0, 0], [1, 0], [1, 1]]},
    {"name": "B", "front": [[0, 0], [1, 0], [1, 1]]},
    {"name": "C", "front": []},
]


def ev(person, event, place, t, **kw):
    return {"person_id": person, "track_id": person, "event": event, "place": place, "time_s": float(t),
            "frame": int(t * 10), "duration_s": None, "confidence": 1.0, "feet_estimated": False, "reason": "", **kw}


EVENTS = [
    ev(1, "enter", "A", 1),                                           # A only
    ev(2, "enter", "A", 2), ev(2, "exit", "A", 12), ev(2, "enter", "B", 20),      # A then B
    ev(3, "enter", "A", 3), ev(3, "enter", "B", 30), ev(3, "enter", "A", 60),    # A, B, then A again
    ev(4, "enter", "B", 4),                                           # B only
    ev(5, "stop", "A", 5, duration_s=4.0),                            # stopped at A, never went in
    ev(6, "peek", "B", 6),                                            # looked in, not counted
]
FRONT = [{"person_id": 7, "place": "A", "front_sec": 2.0, "still_sec": 0.0},      # walked past A
         {"person_id": 5, "place": "A", "front_sec": 5.0, "still_sec": 4.0},
         {"person_id": 1, "place": "A", "front_sec": 1.0, "still_sec": 0.0}]


@pytest.fixture
def result():
    return journeys.summarize(EVENTS, FRONT, PLACES)


def row(result, name):
    return next(r for r in result["places"] if r["name"] == name)


def test_per_shop_counts(result):
    a, b = row(result, "A"), row(result, "B")
    assert (a["entered"], a["entries"], a["reentries"], a["exits"]) == (3, 4, 1, 1)
    assert (b["entered"], b["entries"], b["peeks"]) == (3, 3, 1)
    assert a["entered_ids"] == [1, 2, 3]


def test_average_time_inside_uses_only_visits_with_an_exit(result):
    assert row(result, "A")["avg_inside_s"] == 10.0
    assert row(result, "B")["avg_inside_s"] is None


def test_stopped_and_passed_counts_need_a_front_area(result):
    a, c = row(result, "A"), row(result, "C")
    assert a["stopped"] == 1 and a["passed"] == 1          # person 7 passed; 5 stopped; 1 entered
    assert c["has_front"] is False and c["stopped"] is None and c["passed"] is None


def test_overlap_of_people_who_entered(result):
    ov = result["overlap_entered"]
    combos = {tuple(c["places"]): c["count"] for c in ov["combinations"]}
    assert combos == {("A",): 1, ("A", "B"): 2, ("B",): 1}
    assert ov["people"] == 4
    assert ov["a_not_b"]["A"]["B"] == 1 and ov["a_not_b"]["B"]["A"] == 1


def test_overlap_of_interested_people_includes_those_who_only_stopped(result):
    ov = result["overlap_interested"]
    combos = {tuple(c["places"]): c["person_ids"] for c in ov["combinations"]}
    assert combos[("A",)] == [1, 5] and ov["people"] == 5


def test_transitions_and_journeys_follow_the_order_of_entry(result):
    assert result["transitions"]["A"]["B"] == 2            # persons 2 and 3 went A to B
    assert result["transitions"]["B"]["A"] == 1            # person 3 went back to A
    seqs = {tuple(j["places"]): j["person_ids"] for j in result["journeys"]}
    assert seqs[("A", "B")] == [2] and seqs[("A", "B", "A")] == [3] and seqs[("A",)] == [1]


def test_a_shop_entered_twice_in_a_row_is_one_step_of_the_journey():
    evs = [ev(1, "enter", "A", 1), ev(1, "exit", "A", 5), ev(1, "enter", "A", 9), ev(1, "enter", "B", 20)]
    res = journeys.summarize(evs, [], PLACES)
    assert [tuple(j["places"]) for j in res["journeys"]] == [("A", "B")]


def test_no_events_gives_zeroes_not_errors():
    res = journeys.summarize([], [], PLACES)
    assert all(r["entered"] == 0 for r in res["places"])
    assert res["overlap_entered"]["people"] == 0 and res["journeys"] == []
