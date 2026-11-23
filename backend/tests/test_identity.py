"""Visitor ids in Mall places mode: colour samples, cutting swapped tracks, joining lost ones, and how it is measured."""
import numpy as np
import pytest

import idmetrics
import identity
from identity import CANDIDATE, CONFIRMED

FPS, STRIDE = 24.0, 2
W, H = 640, 400
RED, BLUE, GREEN, BLACK, WHITE, ORANGE = (30, 30, 200), (200, 60, 30), (40, 160, 40), (20, 20, 20), (235, 235, 235), (30, 140, 240)
BOX_H = 200


def colours(shirt, trousers, x=200):
    """A picture with one person drawn in two colours, and their box."""
    frame = np.full((H, W, 3), 128, np.uint8)
    frame[100:200, x:x + 60] = shirt
    frame[200:300, x:x + 60] = trousers
    return frame, (x, 100, x + 60, 300)


def samples(first, last, shirt, trousers, every=6):
    """Colour samples as the sampler saves them, for a person dressed in these colours."""
    frame, box = colours(shirt, trousers)
    s = identity.sample(frame, box, [])
    return [[f, *s] for f in range(first, last + 1, every)]


def walk(first, last, x0, speed=20.0, y1=100):
    """Observations of a person of box height 200 walking right at `speed` pixels per analysed frame."""
    return [(f, x0 + speed * (f - first) / STRIDE, y1, x0 + speed * (f - first) / STRIDE + 60, y1 + BOX_H)
            for f in range(first, last + 1, STRIDE)]


def data_of(tracks, sigs, last_fid=1000):
    return {"width": W, "height": H, "fps": FPS, "stride": STRIDE, "last_fid": last_fid, "tracks": tracks, "signatures": sigs}


def the_link(res, a, b):
    return next((l for l in res["links"] if (l["a"], l["b"]) == (a, b)), None)


# ── Colour samples ────────────────────────────────────────────
def test_same_clothes_match_and_different_clothes_do_not():
    a = identity.Piece(1, 1, walk(0, 60, 100), samples(0, 60, RED, BLACK), FPS, False)
    same = identity.Piece(2, 2, walk(80, 140, 100), samples(80, 140, RED, BLACK), FPS, False)
    other = identity.Piece(3, 3, walk(80, 140, 100), samples(80, 140, GREEN, WHITE), FPS, False)
    assert identity.colour_match(a.shirt, a.trousers, same.shirt, same.trousers) > 0.99
    assert identity.colour_match(a.shirt, a.trousers, other.shirt, other.trousers) < 0.6


def test_a_sample_is_refused_when_the_picture_would_not_show_the_person():
    frame, box = colours(RED, BLUE)
    assert identity.sample(frame, box, []) is not None
    assert identity.sample(frame, (200, 100, 260, 120), []) is None                    # too small
    assert identity.sample(frame, (0, 100, 60, 300), []) is None                       # cut by the left edge
    assert identity.sample(frame, (W - 60, 100, W, 300), []) is None                   # ...and the right
    assert identity.sample(frame, box, [(190, 100, 250, 300)]) is None                 # somebody in front of them
    assert identity.sample(frame, box, [(400, 100, 460, 300)]) is not None             # somebody further away is fine


def test_legs_cut_by_the_bottom_edge_leave_the_trousers_out():
    frame = np.full((H, W, 3), 128, np.uint8)
    frame[100:250, 200:260] = RED
    s = identity.sample(frame, (200, 100, 260, H), [])
    assert s[0] is not None and s[1] is None and s[2] is not None and s[3] is None


def test_sampling_is_spaced_and_never_grows_without_limit(monkeypatch):
    frame, box = colours(RED, BLUE)
    sampler = identity.Sampler(every=3, stride=2)
    for fid in range(0, 40, 2):
        sampler.offer(7, fid, frame, box, [])
    assert [r[0] for r in sampler.samples[7]] == [0, 6, 12, 18, 24, 30, 36]
    monkeypatch.setattr(identity, "MAX_SAMPLES", 10)
    many = identity.Sampler(every=1, stride=1)
    for fid in range(200):
        many.offer(1, fid, frame, box, [])
    rows = many.samples[1]
    assert len(rows) <= 11 and rows[0][0] == 0 and rows[-1][0] > 150   # thinned out, still spanning the whole time


def test_a_sample_not_taken_because_of_overlap_is_tried_again_next_frame():
    frame, box = colours(RED, BLUE)
    sampler = identity.Sampler(every=3, stride=2)
    sampler.offer(1, 0, frame, box, [(190, 100, 250, 300)])
    sampler.offer(1, 2, frame, box, [])
    assert [r[0] for r in sampler.samples[1]] == [2]


# ── Undoing swaps ─────────────────────────────────────────────
def crossing_pair(swap):
    """Two people (red / green) walk toward each other and cross; after crossing, the tracker may hand each the other's id."""
    a = [(f, 100 + 10 * (f // STRIDE), 100, 160 + 10 * (f // STRIDE), 300) for f in range(0, 61, STRIDE)]                 # left to right
    b = [(f, 400 - 10 * (f // STRIDE), 100, 460 - 10 * (f // STRIDE), 300) for f in range(0, 61, STRIDE)]                 # right to left
    cut = 30
    ta = [o for o in a if o[0] <= cut] + [o for o in (b if swap else a) if o[0] > cut]
    tb = [o for o in b if o[0] <= cut] + [o for o in (a if swap else b) if o[0] > cut]
    sa = samples(0, cut - 14, RED, BLACK) + samples(cut + 14, 60, GREEN if swap else RED, WHITE if swap else BLACK)
    sb = samples(0, cut - 14, GREEN, WHITE) + samples(cut + 14, 60, RED if swap else GREEN, BLACK if swap else WHITE)
    return {1: ta, 2: tb}, {1: sa, 2: sb}


def test_overlap_is_found_where_two_people_cross():
    tracks, _ = crossing_pair(swap=False)
    eps = identity.overlap_episodes(tracks, STRIDE, set())
    assert len(eps) == 1 and (eps[0]["a"], eps[0]["b"]) == (1, 2) and eps[0]["f0"] < 30 < eps[0]["f1"]


def test_a_swap_is_undone_by_joining_the_pieces_crosswise():
    tracks, sigs = crossing_pair(swap=True)
    pieces, _, origin, joins, log = identity.resolve_swaps(tracks, sigs, FPS, STRIDE, set())
    assert len(pieces) == 4 and sorted(set(origin.values())) == [1, 2]
    assert len(joins) == 2 and all(origin[a] != origin[b] for a, b, _ in joins)   # track 1's start goes on in track 2's end
    assert len(log) == 1 and log[0]["tracks"] == [1, 2] and log[0]["colours"]
    res = identity.resolve(data_of(tracks, sigs), [])
    who = res["person_of"]     # pieces 1 and 2 are the starts of tracks 1 and 2, pieces 3 and 4 their ends
    assert who[1] == who[4] and who[2] == who[3] and who[1] != who[2]
    assert sorted(v["shirt"] for v in res["visitors"]) == ["#28a028", "#c81e1e"]   # each visitor wears one colour throughout
    assert [l["kind"] for l in res["links"] if l["level"] == CONFIRMED] == ["swap", "swap"]


def test_tracks_that_did_not_swap_are_left_whole():
    tracks, sigs = crossing_pair(swap=False)
    pieces, _, _, joins, log = identity.resolve_swaps(tracks, sigs, FPS, STRIDE, set())
    assert set(pieces) == {1, 2} and joins == [] and log == []


def test_without_colours_a_direction_that_turns_round_still_shows_a_swap():
    tracks, _ = crossing_pair(swap=True)
    _, _, _, joins, log = identity.resolve_swaps(tracks, {}, FPS, STRIDE, set())
    assert len(joins) == 2 and log[0]["colours"] is False


def test_without_colours_two_people_who_just_walk_on_are_not_swapped():
    tracks, _ = crossing_pair(swap=False)
    assert identity.resolve_swaps(tracks, {}, FPS, STRIDE, set())[3] == []


def test_a_track_too_short_after_the_overlap_is_not_judged():
    tracks, sigs = crossing_pair(swap=True)
    tracks = {t: [o for o in obs if o[0] <= 36] for t, obs in tracks.items()}      # only two observations after the crossing
    pieces, _, _, joins, _ = identity.resolve_swaps(tracks, sigs, FPS, STRIDE, set())
    assert set(pieces) == {1, 2} and joins == []


def test_a_fixture_never_changes_a_track():
    walker = walk(0, 100, 100)
    dummy = [(f, 150, 100, 210, 300) for f in range(0, 101, STRIDE)]
    sigs = {1: samples(0, 40, RED, BLACK) + samples(60, 100, GREEN, WHITE), 2: samples(0, 100, BLUE, BLUE)}
    assert identity.overlap_episodes({1: walker, 2: dummy}, STRIDE, skip={2}) == []
    pieces, _, _, joins, _ = identity.resolve_swaps({1: walker, 2: dummy}, sigs, FPS, STRIDE, {2})
    assert set(pieces) == {1, 2} and joins == []


# ── Joining lost tracks ───────────────────────────────────────
def lost_and_found(second_shirt=RED, second_trousers=BLACK, gap=10, x_found=None):
    """One person walks (track 1), is lost for `gap` analysed frames, and is picked up under a new id (track 2)."""
    first = walk(0, 60, 100)
    end_x = first[-1][1]
    start = 60 + gap * STRIDE
    second = walk(start, start + 60, end_x + 20.0 * gap if x_found is None else x_found)
    sigs = {1: samples(0, 60, RED, BLACK), 2: samples(start, start + 60, second_shirt, second_trousers)}
    return {1: first, 2: second}, sigs


def test_a_lost_person_found_again_nearby_in_the_same_clothes_is_one_visitor():
    tracks, sigs = lost_and_found()
    res = identity.resolve(data_of(tracks, sigs), [])
    link = the_link(res, 1, 2)
    assert link["level"] == CONFIRMED and link["kind"] == "gap"
    assert res["person_of"][1] == res["person_of"][2]
    assert [v["label"] for v in res["visitors"]] == ["V001"] and res["visitors"][0]["tracks"] == [1, 2]


def test_different_clothes_are_not_joined_even_where_the_position_fits():
    tracks, sigs = lost_and_found(second_shirt=GREEN, second_trousers=WHITE)
    res = identity.resolve(data_of(tracks, sigs), [])
    assert res["links"] == [] and res["person_of"][1] != res["person_of"][2]
    assert [v["label"] for v in res["visitors"]] == ["V001", "V002"]


def test_a_piece_that_appears_far_from_where_the_person_was_heading_is_not_joined():
    tracks, sigs = lost_and_found(x_found=500)
    res = identity.resolve(data_of(tracks, sigs), [])
    assert the_link(res, 1, 2) is None and res["person_of"][1] != res["person_of"][2]


def test_a_person_lost_for_longer_than_the_memory_is_not_joined():
    tracks, sigs = lost_and_found(gap=40)    # 80 frames = 3.3 s
    assert the_link(identity.resolve(data_of(tracks, sigs), [], memory_sec=3.0), 1, 2) is None
    assert the_link(identity.resolve(data_of(tracks, sigs), [], memory_sec=6.0), 1, 2)["level"] == CONFIRMED


def test_pieces_without_colour_samples_are_never_joined():
    tracks, _ = lost_and_found()
    assert identity.resolve(data_of(tracks, {}), [])["links"] == []


def test_two_equally_good_candidates_are_not_confirmed():
    """Two people in the same clothes both start where the lost person would: which one it is cannot be told."""
    first = walk(0, 60, 100)
    start, x = 80, first[-1][1] + 200
    tracks = {1: first, 2: walk(start, start + 60, x, y1=100), 3: walk(start, start + 60, x + 4, y1=104)}
    sigs = {1: samples(0, 60, RED, BLACK), 2: samples(start, start + 60, RED, BLACK), 3: samples(start, start + 60, RED, BLACK)}
    res = identity.resolve(data_of(tracks, sigs), [])
    assert not [l for l in res["links"] if l["level"] == CONFIRMED]
    assert len({res["person_of"][t] for t in tracks}) == 3
    assert any(v["uncertain"] for v in res["visitors"])


def test_leaving_at_the_picture_edge_is_not_taken_as_a_lost_track():
    """Someone who walks out of the picture and, a few seconds later, somebody in the same clothes walks in at the
    same edge: cheap to call them different people (a person really leaves there), so it is not a confirmed link."""
    first = [(f, W - 140 + 10 * (f // STRIDE), 100, W - 80 + 10 * (f // STRIDE), 300) for f in range(0, 13, STRIDE)]
    second = [(f, W - 60 - 10 * ((f - 50) // STRIDE), 100, W - 10 * ((f - 50) // STRIDE), 300) for f in range(50, 71, STRIDE)]
    sigs = {1: samples(0, 12, RED, BLACK, every=2), 2: samples(50, 70, RED, BLACK, every=2)}
    res = identity.resolve(data_of({1: first, 2: second}, sigs), [])
    assert not [l for l in res["links"] if l["level"] == CONFIRMED]


def test_a_chain_of_losses_becomes_one_visitor():
    pieces = [walk(0, 40, 50, speed=8.0)]
    for k in (1, 2):    # each piece starts where the one before was heading: 10 frames after it ended
        pieces.append(walk(50 * k, 50 * k + 40, pieces[-1][-1][1] + 8.0 * 5, speed=8.0))
    tracks = {i + 1: p for i, p in enumerate(pieces)}
    sigs = {i + 1: samples(p[0][0], p[-1][0], RED, BLACK) for i, p in enumerate(pieces)}
    res = identity.resolve(data_of(tracks, sigs), [])
    assert len({res["person_of"][t] for t in tracks}) == 1 and res["visitors"][0]["joined"] == 2


def test_a_return_through_the_same_shop_door_is_joined_only_on_very_close_colours():
    door = {"a": (100.0, 300.0), "b": (260.0, 300.0), "name": "S"}
    into = [(f, 150, 100, 210, 300) for f in range(0, 31, STRIDE)]                       # ends at the door
    out = [(f, 160, 100, 220, 300) for f in range(2000, 2031, STRIDE)]                   # starts there 80 s later
    same = {1: samples(0, 30, RED, BLACK, every=2), 2: samples(2000, 2030, RED, BLACK, every=2)}
    link = the_link(identity.resolve(data_of({1: into, 2: out}, same, last_fid=3000), [door]), 1, 2)
    assert link["kind"] == "door" and link["gap_s"] > 70 and link["level"] == CONFIRMED
    near = {1: same[1], 2: samples(2000, 2030, ORANGE, BLACK, every=2)}   # a different shirt: no link at all
    assert the_link(identity.resolve(data_of({1: into, 2: out}, near, last_fid=3000), [door]), 1, 2) is None


def test_a_return_through_a_door_is_refused_at_a_different_door_or_in_the_walkway():
    doors = [{"a": (100.0, 300.0), "b": (200.0, 300.0), "name": "S1"}, {"a": (400.0, 300.0), "b": (500.0, 300.0), "name": "S2"}]
    into = [(f, 120, 100, 180, 300) for f in range(0, 31, STRIDE)]
    elsewhere = [(f, 420, 100, 480, 300) for f in range(2000, 2031, STRIDE)]
    sigs = {1: samples(0, 30, RED, BLACK, every=2), 2: samples(2000, 2030, RED, BLACK, every=2)}
    assert identity.resolve(data_of({1: into, 2: elsewhere}, sigs, last_fid=3000), doors)["links"] == []


# ── Visitors ──────────────────────────────────────────────────
def test_visitors_are_numbered_by_first_appearance_and_carry_the_colours_they_were_seen_in():
    late = walk(300, 360, 100)
    early = walk(0, 60, 400, speed=-20.0)
    sigs = {1: samples(300, 360, GREEN, WHITE), 2: samples(0, 60, RED, BLACK)}
    res = identity.resolve(data_of({1: late, 2: early}, sigs), [])
    assert res["person_of"] == {2: 1, 1: 2}
    first = res["visitors"][0]
    assert first["label"] == "V001" and first["first_s"] == 0.0 and first["shirt"] == "#c81e1e" and first["trousers"] == "#141414"


def test_a_mannequin_and_a_one_frame_flicker_are_not_visitors():
    dummy = [(f, 150, 100, 210, 300) for f in range(0, 1001, STRIDE)]
    res = identity.resolve(data_of({1: dummy, 2: walk(100, 160, 300), 3: [(500, 10, 10, 70, 210)]},
                                   {2: samples(100, 160, RED, BLACK)}), [])
    assert [v["tracks"] for v in res["visitors"]] == [[2]]
    assert len(set(res["person_of"].values())) == 3          # ...but every track still has an id that is nobody else's
    assert res["fixtures"] == [1]


def test_resolve_with_swaps_off_keeps_the_trackers_tracks():
    tracks, sigs = crossing_pair(swap=True)
    assert set(identity.resolve(data_of(tracks, sigs), [], swaps=False)["pieces"]) == {1, 2}
    assert len(identity.resolve(data_of(tracks, sigs), [], swaps=True)["pieces"]) == 4


def test_resolve_copes_with_nothing_to_do():
    res = identity.resolve(data_of({}, {}), [])
    assert res["visitors"] == [] and res["links"] == [] and res["person_of"] == {}


# ── The measuring tool ────────────────────────────────────────
def labelled_two():
    return {f: [("A", (100, 100, 160, 300)), ("B", (400, 100, 460, 300))] for f in range(0, 20, 2)}


def test_perfect_ids_score_one():
    ours = {f: [(5, (100, 100, 160, 300)), (9, (400, 100, 460, 300))] for f in range(0, 20, 2)}
    s = idmetrics.score(labelled_two(), ours)
    assert s["idf1"] == 1.0 and s["id_switches"] == 0 and s["fragments"] == 0 and s["mixed"] == 0 and s["found"] == 1.0


def test_a_swap_is_counted_as_switches_and_mixed_ids():
    ours = {f: [((5 if f < 10 else 9), (100, 100, 160, 300)), ((9 if f < 10 else 5), (400, 100, 460, 300))]
            for f in range(0, 20, 2)}
    s = idmetrics.score(labelled_two(), ours)
    assert s["id_switches"] == 2 and s["mixed"] == 2 and s["idf1"] == 0.5


def test_a_person_split_over_two_ids_is_a_fragment():
    ours = {f: [((5 if f < 10 else 7), (100, 100, 160, 300)), (9, (400, 100, 460, 300))] for f in range(0, 20, 2)}
    s = idmetrics.score(labelled_two(), ours)
    assert s["fragments"] == 1 and s["id_switches"] == 1 and s["mixed"] == 0 and 0.5 < s["idf1"] < 1.0


def test_frames_where_nothing_was_found_count_as_misses_when_the_analysed_frames_are_given():
    labelled = {f: [("A", (100, 100, 160, 300))] for f in range(0, 20, 2)}
    ours = {f: [(1, (100, 100, 160, 300))] for f in range(0, 10, 2)}            # found in the first five frames only
    assert idmetrics.score(labelled, ours)["found"] == 1.0                      # without the frames, the empty ones are ignored
    s = idmetrics.score(labelled, ours, frames=range(0, 20, 2))
    assert s["found"] == 0.5 and s["idf1"] == 0.667


def test_boxes_nobody_labelled_are_not_found_and_lower_the_score():
    s = idmetrics.score(labelled_two(), {f: [(1, (100, 100, 160, 300))] for f in range(0, 20, 2)})
    assert s["found"] == 0.5 and s["people"] == 1


def test_link_quality_counts_right_and_wrong_confirmed_links():
    labelled = {f: [("A", (100, 100, 160, 300)), ("B", (400, 100, 460, 300))] for f in range(0, 40, 2)}
    pieces = {1: [(f, 100, 100, 160, 300) for f in range(0, 10, 2)], 2: [(f, 100, 100, 160, 300) for f in range(20, 30, 2)],
              3: [(f, 400, 100, 460, 300) for f in range(10, 20, 2)]}
    links = [{"a": 1, "b": 2, "level": "confirmed"}, {"a": 1, "b": 3, "level": "confirmed"}, {"a": 2, "b": 3, "level": "candidate"}]
    q = idmetrics.link_quality(labelled, pieces, links)
    assert (q["right"], q["wrong"], q["unknown"]) == (1, 1, 0) and q["wrong_links"] == [(1, 3, "A", "B")]


def test_caviar_labels_are_read(tmp_path):
    xml = tmp_path / "gt.xml"
    xml.write_text('<dataset><frame number="3"><objectlist><object id="0"><box h="100" w="40" xc="50" yc="80"/></object>'
                   '</objectlist></frame><frame number="4"><objectlist/></frame></dataset>', encoding="utf-8")
    got = idmetrics.load_caviar(str(xml))
    assert got[3] == [("0", (30.0, 30.0, 70.0, 130.0))] and got[4] == []


# ── Knots, rivals and size (found by review) ──────────────────
def patched_knots(monkeypatch, ids, f0, f1, costs, length=200):
    """Tracks that run side by side for `length` frames, one knot around [f0, f1], and chosen same-person costs between them."""
    tracks = {t: [(f, 100 + 40 * t, 100, 160 + 40 * t, 300) for f in range(0, length, STRIDE)] for t in ids}
    monkeypatch.setattr(identity, "overlap_episodes", lambda *_: [{"a": ids[0], "b": ids[1], "f0": f0, "f1": f1}])
    monkeypatch.setattr(identity, "_clusters", lambda eps, gap: [{"tracks": set(ids), "f0": f0, "f1": f1}])
    monkeypatch.setattr(identity, "_around", lambda obs, samples, a, b, fps, stride: {"id": obs[0][1]})
    monkeypatch.setattr(identity, "_same_person_cost", lambda x, y, fps: (costs[(round((x["id"] - 100) / 40), round((y["id"] - 100) / 40))], None))
    return tracks


def test_every_swap_in_a_knot_stands_or_falls_on_its_own(monkeypatch):
    """Tracks 1 and 2 clearly traded places; 3 and 4 only look a little cheaper traded. The strong swap must not carry the weak one."""
    costs = {(a, b): 5.0 if a == b else 9.0 for a in range(1, 5) for b in range(1, 5)}
    costs.update({(1, 2): 1.0, (2, 1): 1.0, (3, 4): 4.8, (4, 3): 4.8})
    tracks = patched_knots(monkeypatch, [1, 2, 3, 4], 60, 70, costs)
    pieces, _, origin, joins, log = identity.resolve_swaps(tracks, {}, FPS, STRIDE, set())
    assert len(pieces) == 6 and [(o, origin[a], origin[b]) for o, (a, b, _) in enumerate(joins)] == [(0, 1, 2), (1, 2, 1)]
    assert len(log) == 1 and log[0]["tracks"] == [1, 2] and log[0]["gain"] == 8.0
    assert joins[0][2]["gain"] == 8.0                                           # the evidence kept is that swap's own


def test_two_people_who_trade_places_twice_are_joined_through_both_knots(monkeypatch):
    costs = {(a, b): 5.0 if a == b else 1.0 for a in (1, 2) for b in (1, 2)}
    tracks = patched_knots(monkeypatch, [1, 2], 60, 70, costs)
    monkeypatch.setattr(identity, "_clusters", lambda eps, gap: [{"tracks": {1, 2}, "f0": 60, "f1": 70}, {"tracks": {1, 2}, "f0": 120, "f1": 130}])
    res = identity.resolve(data_of(tracks, {}), [])
    who = res["person_of"]
    assert len(res["pieces"]) == 6 and len(res["visitors"]) == 2
    first, second = [p for p in res["pieces"] if who[p] == who[1]], [p for p in res["pieces"] if who[p] == who[2]]
    assert len(first) == len(second) == 3 and {res["origin"][p] for p in first} == {1, 2}   # each person was carried by both tracks


def test_a_knot_with_someone_who_cannot_be_judged_is_left_alone(monkeypatch):
    tracks, sigs = crossing_pair(swap=True)
    tracks[3] = [(f, 300, 100, 360, 300) for f in range(40, 52, STRIDE)]     # a third person overlapping the crossing, gone before it ends
    sigs[3] = []
    # the crossing alone is undone (above); with a third track in the knot that has nothing after it, it is not
    third = [(f, 250, 100, 310, 300) for f in range(20, 40, STRIDE)]
    pieces, _, _, joins, _ = identity.resolve_swaps({**tracks, 3: third}, sigs, FPS, STRIDE, set())
    assert joins == [] and set(pieces) == {1, 2, 3}


def test_a_colourless_piece_that_fits_as_well_is_a_rival_and_blocks_confirmation():
    first = walk(0, 60, 100)
    start, x = 80, first[-1][1] + 200
    tracks = {1: first, 2: walk(start, start + 60, x), 3: walk(start, start + 60, x + 4, y1=104)}
    # track 2 is mostly in the same clothes (matches 0.93), a little unlike them; track 3 has no colours at all
    both = {1: samples(0, 60, RED, BLACK), 2: samples(start, start + 29, RED, BLACK) + samples(start + 30, start + 40, GREEN, WHITE)}
    res = identity.resolve(data_of(tracks, both), [])
    assert the_link(res, 1, 2)["level"] == CANDIDATE and res["person_of"][1] != res["person_of"][2]
    alone = identity.resolve(data_of({1: first, 2: tracks[2]}, both), [])
    assert the_link(alone, 1, 2)["level"] == CONFIRMED


def test_the_colours_where_two_pieces_meet_must_match_too():
    """A piece whose end looks like somebody else (the tracker moved on to another person) is not joined on its earlier colours."""
    first = walk(0, 60, 100)
    start = 80
    second = walk(start, start + 60, first[-1][1] + 200)
    mixed = samples(0, 40, RED, BLACK) + samples(48, 60, GREEN, WHITE, every=2)    # starts as the red person, ends as a green one
    sigs = {1: mixed, 2: samples(start, start + 60, RED, BLACK)}
    assert the_link(identity.resolve(data_of({1: first, 2: second}, sigs), []), 1, 2) is None


def test_many_lookalikes_do_not_make_the_work_explode():
    """One colour for everybody, 400 short tracks that could all follow each other: it must finish, not take minutes."""
    import random
    import time
    rng = random.Random(3)
    tracks, sigs = {}, {}
    for t in range(1, 401):
        first = rng.randrange(0, 1400, 2)
        tracks[t] = walk(first, first + 40, rng.uniform(80, 400), speed=rng.uniform(-8, 8), y1=rng.uniform(80, 120))
        sigs[t] = samples(first, first + 40, RED, BLACK)
    t0 = time.time()
    res = identity.resolve(data_of(tracks, sigs, last_fid=1500), [])
    assert time.time() - t0 < 20 and len(res["person_of"]) == 400


def test_the_nearest_door_is_the_one_a_piece_is_at():
    doors = [{"a": (100.0, 300.0), "b": (200.0, 300.0)}, {"a": (210.0, 300.0), "b": (310.0, 300.0)}]
    assert identity._kind((0, 220, 100, 260, 290), (640, 400), doors) == ("door", 1)
    assert identity._kind((0, 150, 100, 190, 290), (640, 400), doors) == ("door", 0)
