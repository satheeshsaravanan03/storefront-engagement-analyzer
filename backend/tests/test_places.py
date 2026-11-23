"""Tests for places.py: zone checks, geometry, feet estimate, door crossings, front area and the whole pipeline."""

import pytest

import places

W, H = 1000, 1000
FPS = 10.0


def place(**over):
    """A shop whose door line is the vertical x = 0.5 from y = 0.4 to 0.7, inside on the right, front area on the left."""
    p = {"name": "Shop A", "door": [[0.5, 0.4], [0.5, 0.7]], "inside": [0.95, 0.55],
         "front": [[0.3, 0.4], [0.5, 0.4], [0.5, 0.7], [0.3, 0.7]]}
    p.update(over)
    return p


@pytest.fixture
def shop():
    return places.to_pixels(places.parse_places([place()]), W, H)[0]


def pts_from(xy, start=0, step=1, body_h=100.0, estimated=False):
    """Feet points of a track: one observation every `step` frames."""
    return [(start + i * step, x, y, estimated, body_h) for i, (x, y) in enumerate(xy)]


def walk(x0, x1, y, speed_px_s=100.0):
    """A straight horizontal walk at the given speed, sampled at FPS."""
    n = int(abs(x1 - x0) / speed_px_s * FPS) + 1
    return [(x0 + (x1 - x0) * i / (n - 1), y) for i in range(n)]


# ── parse_places ──────────────────────────────────────────────
def test_parse_places_accepts_a_valid_shop():
    # Arrange / Act
    out = places.parse_places([place()])

    # Assert
    assert out[0]["id"] == "S1" and out[0]["name"] == "Shop A"
    assert out[0]["door"] == [[0.5, 0.4], [0.5, 0.7]]
    assert len(out[0]["front"]) == 4


def test_parse_places_front_area_is_optional_and_name_defaults():
    out = places.parse_places([place(name="  ", front=None)])
    assert out[0]["front"] == [] and out[0]["name"] == "Shop 1"


@pytest.mark.parametrize("bad", [
    None, [], "x", [5],
    [place(door=[[0.5, 0.4]])],                                  # one point only
    [place(door=[[0.5, 0.4], [0.5, 0.41]])],                     # too short
    [place(door=[[0.5, 0.4], [0.5, 1.2]])],                      # outside the frame
    [place(door=[[0.5, 0.4], [True, 0.7]])],                     # a boolean is not a number
    [place(door=[[0.5, 0.4], [float("nan"), 0.7]])],
    [place(inside=None)],
    [place(inside=[0.5, 0.55])],                                 # on the door line
    [place(front=[[0.1, 0.1], [0.2, 0.2]])],                     # two points is not an area
    [place(front=[[0.1, 0.1], [0.2, 0.2], [0.3, 0.3]])],         # no area
    [place(front=5)],                                            # not a list
    [place(front=True)],
    [place(name=5)],                                             # not text
    [place(door=[[10 ** 400, 0.4], [0.5, 0.7]])],                # an integer too big for a float
    [place(), place(name="shop a")],                             # same name twice
    [place(name=f"S{i}") for i in range(places.MAX_PLACES + 1)],
])
def test_parse_places_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        places.parse_places(bad)


# ── geometry ──────────────────────────────────────────────────
def test_line_side_has_opposite_signs_on_the_two_sides():
    a, b = (0.0, 0.0), (0.0, 10.0)
    assert places.line_side(a, b, (5, 5)) * places.line_side(a, b, (-5, 5)) < 0
    assert places.line_side(a, b, (3, 5)) == pytest.approx(-3.0)


def test_to_pixels_marks_the_inside_side_as_positive(shop):
    inside = (700.0, 550.0)
    assert shop["sign"] * places.line_side(shop["a"], shop["b"], inside) > 0
    assert shop["sign"] * places.line_side(shop["a"], shop["b"], (300.0, 550.0)) < 0
    assert shop["len"] == pytest.approx(300.0)


def test_point_in_polygon():
    sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert places.point_in_polygon(sq, (5, 5))
    assert not places.point_in_polygon(sq, (15, 5))


# ── height model and feet ─────────────────────────────────────
def samples(slope=0.3, offset=120.0, rows=range(300, 951, 10), repeat=2):
    return [(float(y), slope * y + offset) for y in rows for _ in range(repeat)]


def test_height_model_recovers_the_perspective_line():
    model = places.HeightModel.fit(samples(), H)
    assert model.slope == pytest.approx(0.3, abs=0.01)
    assert model.offset == pytest.approx(120.0, abs=3.0)


def test_height_model_ignores_boxes_with_hidden_legs():
    good = samples()
    short = [(y, h * 0.6) for y, h in good[::5]]       # 20% of the boxes are cut off
    model = places.HeightModel.fit(good + short, H)
    assert model.slope == pytest.approx(0.3, abs=0.02)              # a flat fallback would not pass this
    assert model.height_at(600) == pytest.approx(0.3 * 600 + 120, rel=0.03)


def test_height_model_is_flat_when_people_stay_on_one_row():
    model = places.HeightModel.fit([(500.0 + i % 3, 200.0) for i in range(60)], H)
    assert model.slope == 0.0 and model.offset == pytest.approx(200.0)


def test_height_model_needs_enough_samples():
    assert places.HeightModel.fit(samples(rows=range(300, 340, 10), repeat=1), H) is None


def test_height_model_is_refused_when_rows_are_alike_but_heights_differ():
    # a corridor view: nearly everyone far away on a few rows, a few people close and much taller
    far = [(300.0 + i % 4, 60.0 + i % 5) for i in range(50)]
    near = [(310.0, 220.0)] * 8
    assert places.HeightModel.fit(far + near, H) is None


def test_height_model_is_refused_when_the_fit_is_noisy():
    noisy = [(float(y), (0.3 * y + 120) * (0.4 if i % 2 else 1.6)) for i, y in enumerate(range(300, 950, 8))]
    assert places.HeightModel.fit(noisy, H) is None


def test_feet_from_head_is_one_body_height_below_the_head():
    model = places.HeightModel(0.3, 120.0)
    feet = 700.0
    head = feet - model.height_at(feet)
    assert model.feet_from_head(head) == pytest.approx(feet)


def test_track_feet_trusts_a_whole_body_box():
    model = places.HeightModel(0.3, 120.0)
    top, bottom = 700 - 330, 700                        # 330 = height at row 700
    out = places.track_feet([(0, 100, top, 140, bottom)], model, H)
    assert out[0][2] == 700 and out[0][3] is False


def test_track_feet_estimates_hidden_legs_from_the_head():
    model = places.HeightModel(0.3, 120.0)
    top = 700 - 330
    cut = 700 - 0.4 * 330                               # legs hidden: the box ends 40% too early
    out = places.track_feet([(0, 100, top, 140, cut)], model, H)
    assert out[0][3] is True
    assert out[0][2] == pytest.approx(700, abs=1)


def test_track_feet_estimates_feet_below_the_frame_edge():
    model = places.HeightModel(0.3, 120.0)
    out = places.track_feet([(0, 100, 600, 160, H - 1)], model, H)    # box touches the bottom edge
    assert out[0][3] is True and out[0][2] > H - 1


def test_track_feet_does_not_mistake_a_short_person_for_hidden_legs():
    model = places.HeightModel(0.3, 120.0)
    child = 0.75 * model.height_at(700)                  # a child with feet in plain view
    obs = [(i, 100 + i, 700 - child, 100 + i + child / 2.4, 700) for i in range(8)]
    out = places.track_feet(obs, model, H)
    assert all(not p[3] for p in out)
    assert all(p[2] == 700 for p in out)


def test_track_feet_still_estimates_a_short_persons_hidden_legs():
    model = places.HeightModel(0.3, 120.0)
    child = 0.75 * model.height_at(700)
    whole = [(i, 100 + i, 700 - child, 100 + i + child / 2.4, 700) for i in range(8)]
    cut = [(8, 108, 700 - child, 108 + child / 2.4, 700 - 0.4 * child)]       # the same child, legs hidden
    out = places.track_feet(whole + cut, model, H)
    assert out[-1][3] is True
    assert out[-1][2] == pytest.approx(700, abs=3)


def test_track_feet_without_a_model_uses_the_box_bottom():
    out = places.track_feet([(0, 100, 600, 160, 800)], None, H)
    assert out[0][2] == 800 and out[0][3] is False


# ── door crossings ────────────────────────────────────────────
def events(pts, shop, last_fid=1000, stay=2.5):
    return places.shop_events(pts, shop, FPS, stay, last_fid, (W, H))


def kinds(evs):
    return [e["event"] for e in evs]


def test_walking_in_and_staying_is_an_entry(shop):
    pts = pts_from(walk(380, 800, 550))                 # crosses x = 500 and keeps walking inside for 3 s
    evs = events(pts, shop)
    assert kinds(evs) == ["enter"] and evs[0]["reason"] == "stay"
    assert evs[0]["time_s"] == pytest.approx(1.2, abs=0.1)


def test_walking_in_and_disappearing_is_an_entry(shop):
    pts = pts_from(walk(380, 600, 550))                 # track ends 1 s after the door, long before the video ends
    evs = events(pts, shop, last_fid=1000)
    assert kinds(evs) == ["enter"] and evs[0]["reason"] == "vanish"


def test_stepping_in_and_straight_back_out_is_a_peek(shop):
    out = walk(380, 600, 550)
    pts = pts_from(out + out[::-1])
    evs = events(pts, shop)
    assert kinds(evs) == ["peek"]


def test_entering_then_leaving_after_a_stay_gives_enter_and_exit(shop):
    path = walk(380, 700, 550) + [(700, 550)] * 30 + walk(700, 380, 550)
    evs = events(pts_from(path), shop)
    assert kinds(evs) == ["enter", "exit"]
    assert evs[0]["time_s"] < evs[1]["time_s"]


def test_someone_first_seen_inside_who_walks_out_is_an_exit(shop):
    evs = events(pts_from(walk(700, 380, 550)), shop)
    assert kinds(evs) == ["exit"]


def test_jitter_on_the_door_line_is_not_a_crossing(shop):
    wobble = [(500 + (6 if i % 2 else -6), 550) for i in range(40)]      # inside the 15 px dead band
    assert events(pts_from(wobble), shop) == []


def test_a_single_stray_observation_beyond_the_band_is_not_a_crossing(shop):
    path = [(450, 550)] * 6 + [(540, 550)] + [(450, 550)] * 6
    assert events(pts_from(path), shop) == []


def test_walking_past_the_end_of_the_door_line_is_ignored(shop):
    assert events(pts_from(walk(380, 700, 900)), shop) == []             # the line stops at y = 700


def test_walking_along_the_front_without_crossing_is_ignored(shop):
    assert events(pts_from(walk(100, 450, 550)), shop) == []


def test_a_long_detour_out_of_the_shop_area_is_neither_an_entry_nor_a_peek(shop):
    # across the door line, a long walk along the walkway past the end of the shop area, then back across the line
    # far from the door: not a peek (the old interpolation squeezed the exit up against the entry), and not an
    # entry either, because the person walked on past the shop area instead of staying in it
    path = (walk(380, 520, 550) + [(520, y) for y in range(560, 971, 40)]
            + [(x, 970) for x in range(500, 200, -40)] + [(200, y) for y in range(930, 549, -40)])
    assert events(pts_from(path), shop) == []


def test_a_track_that_starts_on_the_door_line_and_walks_out_is_an_exit(shop):
    path = [(502, 550), (499, 550)] + [(x, 550) for x in range(480, 390, -10)]
    assert kinds(events(pts_from(path), shop)) == ["exit"]


def shop_with(**over):
    return places.to_pixels(places.parse_places([place(**over)]), W, H)[0]


def test_the_pin_sets_the_direction_and_the_depth_of_the_shop_area():
    s = shop_with(inside=[0.7, 0.45])                  # door middle is (500, 550); the pin is 200 right and 100 up
    assert s["pin"] == (700.0, 450.0)
    assert s["inward"] == pytest.approx((0.894, -0.447), abs=0.001)
    assert s["region"] == [(500.0, 400.0), (500.0, 700.0), (700.0, 600.0), (700.0, 300.0)]   # the door line moved by the pin offset


def test_walking_along_the_door_line_is_not_walking_into_the_shop(shop):
    # a steep diagonal that happens to cross the line: it moves along the door, not toward the pin
    path = [(480 + 40 * i / 30, 420 + 280 * i / 30) for i in range(31)]
    assert events(pts_from(path), shop) == []


def test_heading_away_from_the_pin_is_not_an_entry_even_if_the_feet_cross_the_line():
    # the pin is up and to the right, so the way in is up and to the right; this walker crosses going down
    s = shop_with(inside=[0.7, 0.3])
    path = [(480 + i * 4.0, 480 + i * 8.0) for i in range(12)]
    assert events(pts_from(path), s) == []


def test_walking_on_past_the_shop_area_is_not_an_entry():
    s = shop_with(inside=[0.7, 0.55])                  # the shop area ends 200 px past the line
    assert events(pts_from(walk(380, 900, 550)), s) == []


def test_a_track_that_ends_at_the_edge_of_the_picture_has_left_the_picture_not_gone_into_a_shop():
    s = shop_with(door=[[0.9, 0.4], [0.9, 0.7]], inside=[0.995, 0.55])
    assert events(pts_from(walk(800, 1000, 550)), s) == []
    mid = shop_with(door=[[0.5, 0.4], [0.5, 0.7]], inside=[0.95, 0.55])
    assert kinds(events(pts_from(walk(380, 600, 550)), mid)) == ["enter"]        # the same walk away from the edge counts


def test_a_track_that_vanishes_far_from_the_door_is_not_an_entry(shop):
    path = walk(380, 560, 550) + [(560, 550 + 40 * i) for i in range(1, 9)]       # across the line, then off down the walkway
    assert events(pts_from(path), shop) == []


def test_the_dead_band_grows_with_the_size_of_the_person(shop):
    step = [(480, 550)] * 4 + [(520, 550)] * 4 + [(520, 550)] * 30                 # 20 px either side of the line
    assert events(pts_from(step, body_h=300.0), shop) == []                        # a tall person: inside the 30 px band
    assert kinds(events(pts_from(step, body_h=50.0), shop)) == ["enter"]           # a small one: a clear crossing


def test_a_short_door_does_not_reach_a_person_standing_at_the_next_door():
    # a door seen end-on is only 40 px long on screen; a 100 px tall person must not stretch it by half a body each way
    s = shop_with(door=[[0.5, 0.40], [0.5, 0.44]], inside=[0.95, 0.42])
    assert places.door_crossings(pts_from(walk(380, 600, 470)), s) == []        # 30 px beyond the end of the line
    assert len(places.door_crossings(pts_from(walk(380, 600, 445)), s)) == 1    # 5 px beyond: still the door


def test_walking_straight_at_the_door_and_being_hidden_just_short_of_the_line_is_a_weak_entry(shop):
    path = [(x, 550) for x in range(380, 491, 10)]                              # ends 10 px short of the line
    evs = events(pts_from(path), shop)
    assert kinds(evs) == ["enter"] and evs[0]["reason"] == "vanish" and evs[0]["confidence"] < 1.0


@pytest.mark.parametrize("path", [
    [(x, 550) for x in range(380, 441, 10)],                    # ends far from the line
    [(490, 400 + 10 * i) for i in range(15)],                   # walks along the door, not toward the pin
    [(490, 550)] * 15,                                          # stands there
    [(x, 550) for x in range(500, 380, -10)],                   # walks away from the door
], ids=["far", "along", "standing", "away"])
def test_a_track_that_ends_near_the_door_without_heading_into_it_is_not_an_entry(shop, path):
    assert "enter" not in kinds(events(pts_from(path), shop))


def test_a_clear_step_inside_that_never_held_dates_the_crossing_at_the_step(shop):
    path = [(300, 550)] * 3 + [(520, 550)] + [(507, 550)] * 12                  # a step in, then waits on the line
    crossing = places.door_crossings(pts_from(path), shop)[0]
    assert crossing["dir"] == "in" and crossing["fid"] < 5                      # not at the end of the track (fid 15)


def test_there_is_no_gray_zone_between_a_peek_and_a_stay(shop):
    # in, wait in the shop area, back out: whatever the wait, it is a peek or an entry plus an exit, never nothing
    for waiting in range(10, 40):
        path = [(x, 550) for x in range(380, 520, 10)] + [(520, 550)] * waiting + [(x, 550) for x in range(510, 380, -10)]
        pts = pts_from(path)
        c_in, c_out = places.door_crossings(pts, shop)
        inside = (c_out["fid"] - c_in["fid"]) / FPS
        assert kinds(events(pts, shop)) == (["peek"] if inside < 2.5 else ["enter", "exit"]), (waiting, inside)


def test_a_wobble_beside_the_line_at_the_start_of_a_track_is_not_an_exit(shop):
    # first seen on the line, then a step to 10 px outside: less than the clear step (2 bands = 20 px) it takes
    path = [(505, 550), (505, 550), (490, 550), (490, 550), (490, 550), (505, 550), (505, 550)]
    assert events(pts_from(path), shop) == []


def test_vanishing_just_past_the_door_line_is_a_weak_entry(shop):
    path = [(x, 550) for x in range(380, 500, 10)] + [(512, 550)]            # last seen 12 px inside, in the band
    evs = events(pts_from(path), shop)
    assert kinds(evs) == ["enter"] and evs[0]["reason"] == "vanish"
    assert evs[0]["confidence"] < events(pts_from(walk(380, 600, 550)), shop)[0]["confidence"]


def test_ending_on_the_door_line_without_going_past_it_is_not_an_entry(shop):
    path = [(x, 550) for x in range(380, 500, 10)] + [(503, 550)]            # stopped at the threshold
    assert events(pts_from(path), shop) == []


def test_a_track_cut_by_the_end_of_the_video_is_a_low_confidence_entry(shop):
    pts = pts_from(walk(380, 560, 550))                 # still walking in when the video ends
    evs = events(pts, shop, last_fid=pts[-1][0])
    assert kinds(evs) == ["enter"] and evs[0]["reason"] == "end_of_video"
    assert evs[0]["confidence"] < 0.7


def test_confidence_drops_when_the_feet_were_estimated(shop):
    sure = events(pts_from(walk(380, 800, 550)), shop)[0]["confidence"]
    guessed = events(pts_from(walk(380, 800, 550), estimated=True), shop)[0]
    assert guessed["feet_estimated"] is True and guessed["confidence"] < sure


# ── front area ────────────────────────────────────────────────
def test_standing_in_the_front_area_counts_as_slow_time(shop):
    pts = pts_from([(400, 550)] * 40)
    st = places.front_stats(pts, shop, FPS)
    assert st["still_sec"] >= 3.0 and st["stop_start_s"] is not None


def test_walking_through_the_front_area_is_not_slow_time(shop):
    st = places.front_stats(pts_from(walk(320, 480, 550)), shop, FPS)
    assert st["front_sec"] > 0.5 and st["still_sec"] == 0.0


def test_separate_short_pauses_do_not_add_up_to_a_stop(shop):
    # three 1.5 s pauses with fast walking between them: 4.5 s standing in all, but never 3 s in one go
    path = []
    for _ in range(3):
        path += [(330, 550)] * 15 + [(330 + 30 * i, 580) for i in range(1, 6)] + [(330, 550)]
    st = places.front_stats(pts_from(path), shop, FPS)
    assert 1.0 <= st["still_sec"] < 2.5


def test_front_stats_is_none_without_a_front_area():
    bare = places.to_pixels(places.parse_places([place(front=None)]), W, H)[0]
    assert places.front_stats(pts_from([(400, 550)] * 5), bare, FPS) is None


# ── whole pipeline on a simulated camera ──────────────────────
SLOPE, OFFSET = 0.3, 120.0


def box(x, feet_y, hidden=0.0):
    """Pixel box of a standing person whose feet are at (x, feet_y); `hidden` is the share of the legs cut off."""
    h = SLOPE * feet_y + OFFSET
    return (x - h / 4.8, feet_y - h, x + h / 4.8, feet_y - hidden * h)


def track(path, start=0, hidden=lambda x: 0.0):
    return [(start + i, *box(x, y, hidden(x))) for i, (x, y) in enumerate(path)]


def background_walkers():
    """Walkers on many rows so the height model has something to learn from; they never reach the door."""
    return {100 + k: track(walk(100, 250, y), start=k) for k, y in enumerate(range(300, 960, 25))}


def run(tracks, **kw):
    tracks = {**background_walkers(), **tracks}
    last = max(o[0] for obs in tracks.values() for o in obs)
    return places.analyze(tracks, {}, places.parse_places([place()]), W, H, FPS, last, **kw)


def of(res, tid, event=None):
    return [e for e in res["events"] if e["track_id"] == tid and (event is None or e["event"] == event)]


def test_pipeline_counts_each_kind_of_visit():
    res = run({
        1: track(walk(380, 800, 550)),                                           # walks in and stays
        2: track(walk(380, 600, 560), start=5),                                  # walks in and vanishes
        3: track(walk(380, 600, 540) + walk(600, 380, 540), start=8),            # peek
        4: track(walk(100, 480, 900), start=2),                                  # walks past below the door
    })
    assert [e["reason"] for e in of(res, 1, "enter")] == ["stay"]
    assert [e["reason"] for e in of(res, 2, "enter")] == ["vanish"]
    assert [e["event"] for e in of(res, 3)] == ["peek"]
    assert of(res, 4) == []
    assert res["height_model"]["slope"] == pytest.approx(SLOPE, abs=0.02)


def test_pipeline_enters_with_hidden_legs_and_flags_the_estimate():
    legs = lambda x: 0.4 if 440 <= x <= 560 else 0.0                              # a crowd hides the legs at the door (x = 500)
    res = run({1: track(walk(380, 800, 550), hidden=legs)})
    enter = of(res, 1, "enter")
    assert len(enter) == 1 and enter[0]["feet_estimated"] is True
    assert res["estimated_share"] > 0


def test_a_walker_in_front_of_the_shop_with_hidden_legs_is_not_an_entry():
    # feet at row 950 are far below the door line (it ends at y = 700); the cut-off box bottom lands at about 808
    # and looks much closer. The feet are worked out from the head, which puts them off the end of the line
    walker = {1: track(walk(380, 800, 950), hidden=lambda x: 0.35)}
    res = run(walker)
    assert of(res, 1) == []
    assert res["estimated_share"] > 0


def test_a_mannequin_that_never_moves_is_not_a_visitor():
    # a track there for the whole 25 s whose feet barely move, standing in the front area beside the door line
    still = [(405.0 + (i % 3), 560.0 + (i % 2)) for i in range(250)]
    res = run({1: track(still), 2: track(walk(380, 800, 550), start=0)})
    assert of(res, 1) == []
    assert all(r["person_id"] != 1 for r in res["front"])
    assert 1 not in res["feet"]
    assert [e["event"] for e in of(res, 2)] == ["enter"]          # a person walking in is still counted


def test_a_person_who_stands_still_for_part_of_the_video_is_still_counted():
    res = run({1: track([(400.0, 550.0)] * 120, start=40), 2: track(walk(100, 250, 300), start=0)})
    stops = [e for e in res["events"] if e["person_id"] == 1]      # a stop belongs to the person, not one track
    assert [e["event"] for e in stops] == ["stop"]                 # 12 s still, but not for 90% of a 16 s video


def test_pipeline_joins_tracks_of_the_same_person():
    first = track(walk(380, 560, 550))                                           # lost right after the door
    second = track(walk(700, 380, 550), start=60)                                # someone appears inside and leaves
    res = places.analyze({**background_walkers(), 1: first, 2: second}, {1: 7, 2: 7},
                         places.parse_places([place()]), W, H, FPS, 1000)
    assert {e["person_id"] for e in res["events"]} == {7}
    assert [e["event"] for e in res["events"]] == ["enter", "exit"]


def test_pipeline_reports_stops_and_passes():
    res = run({
        1: track([(400.0, 550.0)] * 45),                                         # stands in front for 4.5 s
        2: track(walk(320, 480, 600), start=3),                                  # walks across the front area
    })
    assert [e["event"] for e in res["events"] if e["person_id"] == 1] == ["stop"]
    rows = {r["person_id"]: r for r in res["front"]}
    assert rows[1]["still_sec"] >= 3.0 and rows[2]["still_sec"] == 0.0
