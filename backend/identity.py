"""
identity.py
===========
Who is who in Mall places mode: keeps one visitor id (V001, V002, ...) on a person for the whole video, even
when the tracker loses them and hands out a new track id, or swaps two people who walked past each other.

The tracker's id (track_id) is only a temporary label. This module works on what the tracker saved:

  1. SAMPLE  while tracking, a few colour samples of the shirt and the trousers of each track (never the face),
             taken only when the person is not overlapped by anybody else.
  2. SWAPS   where people overlapped, the people who carry on are matched again with the people who were there
             before (colours, movement). The tracker's own pairing stands unless another one is clearly better.
  3. LINK    the pieces are joined into visitors by what they share: shirt and trousers colour, where the
             earlier piece was heading and where the later one appears, how long the gap is, and whether
             the earlier piece ended somewhere a person really leaves (picture edge, a shop door).
  4. CONFIDENCE every link is confirmed, candidate or unknown. Only confirmed links join pieces into one
             visitor; the counts use visitors. A wrong join is worse than a missed one, so when two answers
             are close the pieces stay apart. Each link keeps its evidence.

Only the sampling needs a picture (cv2); everything else is plain numbers, so it is tested without video.
"""

import base64
import math
from bisect import bisect_right
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import min_weight_full_bipartite_matching

import places as places_mod

# Where on the person box the shirt and the trousers are read: (y0, y1, x0, x1) as fractions of the box
REGIONS = {
    "shirt":    (0.20, 0.50, 0.20, 0.80),
    "trousers": (0.55, 0.88, 0.25, 0.75),
}
BINS = (12, 3, 4)          # hue, saturation, value
MIN_SAMPLE_H = 32          # a box shorter than this (pixels) is too small to read colours from
MAX_OVERLAP = 0.10         # no sample while another person covers more than this share of the box
EDGE_PX = 2
MAX_SAMPLES = 240          # per track; past this the oldest half is thinned out, so a sample is kept from the whole life


def _signature(crop: np.ndarray) -> Optional[str]:
    """Colours of one region as base64 text: the square root of the HSV histogram, one byte per bin."""
    if crop.shape[0] < 6 or crop.shape[1] < 6:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h = cv2.calcHist([hsv], [0, 1, 2], None, list(BINS), [0, 180, 0, 256, 0, 256]).flatten()
    total = h.sum()
    if total <= 0:
        return None
    return base64.b64encode(np.round(np.sqrt(h / total) * 255).astype(np.uint8).tobytes()).decode("ascii")


def _median_rgb(crop: np.ndarray) -> Optional[List[int]]:
    if crop.shape[0] < 6 or crop.shape[1] < 6:
        return None
    b, g, r = np.median(crop.reshape(-1, 3), axis=0)
    return [int(r), int(g), int(b)]


def decode(text: Optional[str]) -> Optional[np.ndarray]:
    """The unit-length vector of a saved signature: the dot product of two of them is their colour match, 0 to 1."""
    if not text:
        return None
    v = np.frombuffer(base64.b64decode(text), dtype=np.uint8).astype(np.float64)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else None


def _covered(box: Sequence[float], other: Sequence[float]) -> float:
    """The share of `box` that `other` covers."""
    ix = max(0.0, min(box[2], other[2]) - max(box[0], other[0]))
    iy = max(0.0, min(box[3], other[3]) - max(box[1], other[1]))
    area = (box[2] - box[0]) * (box[3] - box[1])
    return ix * iy / area if area > 0 else 1.0


def sample(frame: np.ndarray, box: Sequence[float], others: Sequence[Sequence[float]]) -> Optional[list]:
    """
    One colour sample [shirt, trousers, shirt_rgb, trousers_rgb] of the person in `box`, or None when the picture
    would not show them clearly: too small, cut by the left or right edge, or covered by somebody else.
    The trousers are left out when the frame's bottom edge cuts the legs off.
    """
    x1, y1, x2, y2 = (int(round(v)) for v in box)
    fh, fw = frame.shape[:2]
    if y2 - y1 < MIN_SAMPLE_H or x1 <= EDGE_PX or x2 >= fw - EDGE_PX:
        return None
    if any(_covered(box, o) > MAX_OVERLAP for o in others):
        return None
    h, w = y2 - y1, x2 - x1
    out: list = []
    rgbs: list = []
    for name, (a, b, c, d) in REGIONS.items():
        crop = frame[max(0, int(y1 + a * h)):int(y1 + b * h), max(0, int(x1 + c * w)):int(x1 + d * w)]
        legs_cut = name == "trousers" and y2 >= fh - EDGE_PX
        out.append(None if legs_cut else _signature(crop))
        rgbs.append(None if legs_cut else _median_rgb(crop))
    return out + rgbs if out[0] is not None else None


class Sampler:
    """Collects the colour samples of every track while the video is read. `every` is in analysed frames."""

    def __init__(self, every: int, stride: int):
        self.step = max(1, every) * max(1, stride)   # video frames between two samples of one track
        self.samples: Dict[int, list] = {}           # track id -> [[fid, shirt, trousers, shirt_rgb, trousers_rgb]]
        self._due: Dict[int, int] = {}
        self._step: Dict[int, int] = {}

    def offer(self, tid: int, fid: int, frame: np.ndarray, box: Sequence[float], others: Sequence[Sequence[float]]):
        if fid < self._due.get(tid, 0):
            return
        s = sample(frame, box, others)
        if s is None:
            return   # not clear now: try again on the next frame
        rows = self.samples.setdefault(tid, [])
        rows.append([fid, *s])
        step = self._step.setdefault(tid, self.step)
        self._due[tid] = fid + step
        if len(rows) > MAX_SAMPLES:
            del rows[1::2]
            self._step[tid] = step * 2


# ── Settings ──────────────────────────────────────────────────
MEMORY_SEC = (8.0, 1.0, 60.0)    # default, lowest, highest: how long a lost person is waited for before a new id is final
DOOR_RETURN_SEC = 300.0          # someone who went into a shop may come back out of the same door this much later
MIN_LINK_OBS = 3                 # a piece with fewer observations is noise: never joined to anything

SWAP_COVER = 0.35                # two people overlap when the smaller box is covered at least this much...
SWAP_EPISODE_OBS = 2             # ...in this many analysed frames in a row
SWAP_GAP_SEC = 1.0               # overlaps of the same people closer together than this are one knot of people
SWAP_WINDOW_SEC = 1.0            # position and walking are read from this long before and after a knot
SWAP_COLOUR_SEC = 3.0            # ...and colours from this long
SWAP_MIN_OBS = 3                 # a track needs this many observations on each side of a knot to be judged
SWAP_NEUTRAL = 0.6               # colour match assumed when a side has no colours (the same for every pairing)
SWAP_MARGIN = 1.0                # the tracker's pairing is changed only when another pairing is this much cheaper
W_VELOCITY = 0.5                 # weight of a change in walking, against distance from the prediction (body heights)

SHIRT_WEIGHT = 0.55              # the shirt counts a little more than the trousers
MIN_SIM = 0.70                   # colours matching less than this are different people
MIN_PIECE_SAMPLES = 2            # colour samples a piece needs before its colours are used
EDGE_SAMPLES = 2                 # the colours at the very start and end of a piece are checked from this many samples
TOL_BODY = 0.5                   # a piece may start this many body heights from where the earlier one was heading...
TOL_PER_SEC = 0.7                # ...plus this many for every second it was lost
PREDICT_SEC = 2.0                # a walking person is followed forward for at most this long, then assumed to stop
MAX_RATIO = 1.5                  # a piece starting further than this many tolerances from the prediction is not a candidate
SPEED_WINDOW_SEC = 1.0           # direction and speed are read from this much of the piece's start or end
MOVING = 0.15                    # body heights per second; slower is standing
SIZE_LOG = 0.35                  # |ln(height ratio)| allowed between the two pieces, plus SIZE_LOG_PER_SEC for every second lost
SIZE_LOG_PER_SEC = 0.1

EDGE_BODY = 0.25                 # a piece starts or ends at the picture's edge within this many body heights of it
DOOR_BODY = 1.0                  # ...or at a shop's door within this many
W_APPEARANCE = 4.0               # cost of the link: colour mismatch, distance from the prediction, gap, direction
W_MOTION = 0.5
W_GAP = 0.3
W_DIRECTION = 0.3
W_DOOR = 0.5                     # a return through a shop door has no motion to go by: a base cost instead
LEAVE_PLAUSIBLE = 0.6            # cost of leaving a piece's end (or start) unlinked where a person really leaves (edge, door, video edge)
LEAVE_MIDWAY = 1.2               # ...and where they would not (mid-walkway): the person is probably still there
BIG = 1e6

CONFIRM_SIM = 0.82               # confirmed link: the colours match at least this well,
CONFIRM_RATIO = 1.0              # ...the new piece starts within one tolerance of the prediction,
CONFIRM_MARGIN = 0.6             # ...and the next best candidate (for either piece) costs this much more
CONFIRM_DOOR_SIM = 0.90          # a return through a door is confirmed only on very close colours
ASSUMED_MATCH = CONFIRM_SIM      # a piece with no colours is taken to match this well when it rivals a join
KEEP_BEST = 5                    # each end keeps its cheapest few followers, and each start its cheapest few predecessors
MAX_LINK_PIECES = 4000           # with more pieces than this nothing is joined (the work grows with the square of them)

CONFIRMED, CANDIDATE = "confirmed", "candidate"


def label(visitor: int) -> str:
    return f"V{visitor:03d}"


# ── Pieces of tracks ──────────────────────────────────────────
class Piece:
    """A stretch of one track that is believed to be one person."""

    def __init__(self, pid: int, tid: int, obs: list, samples: list, fps: float, fixture: bool):
        self.pid, self.tid, self.obs, self.samples, self.fixture = pid, tid, obs, samples, fixture
        self.f0, self.f1 = obs[0][0], obs[-1][0]
        arr = np.asarray(obs, dtype=np.float64)
        self.centre = np.column_stack([(arr[:, 1] + arr[:, 3]) / 2.0, (arr[:, 2] + arr[:, 4]) / 2.0])
        self.height = arr[:, 4] - arr[:, 2]
        self.frames = arr[:, 0]
        self.fps = fps
        self.shirt, self.trousers = _mean_signature(samples)
        enough = len(samples) >= EDGE_SAMPLES
        self.head = _mean_signature(samples[:EDGE_SAMPLES]) if enough else (None, None)
        self.tail = _mean_signature(samples[-EDGE_SAMPLES:]) if enough else (None, None)
        self.v_start, self.h_start = self._motion(False)
        self.v_end, self.h_end = self._motion(True)

    def _motion(self, end: bool) -> Tuple[Optional[np.ndarray], float]:
        """Velocity in pixels per second (None when too short to tell) and a body height, at the end or start."""
        n = len(self.frames)
        k = min(n, 5)
        height = float(np.median(self.height[n - k:] if end else self.height[:k]))
        edge = self.frames[-1] if end else self.frames[0]
        idx = np.where(np.abs(self.frames - edge) <= SPEED_WINDOW_SEC * self.fps)[0]
        if len(idx) < 3 or (self.frames[idx[-1]] - self.frames[idx[0]]) / self.fps < 0.3:
            return None, height
        t = (self.frames[idx] - edge) / self.fps
        return np.array([np.polyfit(t, self.centre[idx, 0], 1)[0], np.polyfit(t, self.centre[idx, 1], 1)[0]]), height

    def seconds(self) -> float:
        return (self.f1 - self.f0) / self.fps


def _mean_signature(samples: list) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """The average shirt and trousers colour vectors of a piece's samples (None when it has too few)."""
    out: List[Optional[np.ndarray]] = []
    for col in (1, 2):
        vecs = [v for v in (decode(s[col]) for s in samples) if v is not None]
        if len(vecs) < MIN_PIECE_SAMPLES:
            out.append(None)
            continue
        m = np.mean(vecs, axis=0)
        n = float(np.linalg.norm(m))
        out.append(m / n if n > 0 else None)
    return out[0], out[1]


def colour_match(a_shirt, a_trousers, b_shirt, b_trousers) -> Optional[float]:
    """How alike two people look, 0 to 1: shirt and trousers colours together. None when the shirts cannot be compared."""
    if a_shirt is None or b_shirt is None:
        return None
    shirt = float(np.dot(a_shirt, b_shirt))
    if a_trousers is None or b_trousers is None:
        return shirt
    return SHIRT_WEIGHT * shirt + (1.0 - SHIRT_WEIGHT) * float(np.dot(a_trousers, b_trousers))


# ── Step 2: undo swaps where people overlapped ────────────────
def _cover(a: Sequence[float], b: Sequence[float]) -> float:
    """The share of the smaller of two boxes that the other covers."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return ix * iy / small if small > 0 else 0.0


def overlap_episodes(tracks: Dict[int, list], stride: int, skip: set) -> List[dict]:
    """Where two tracked people overlapped: [{a, b, f0, f1}] with the frames of the first and last overlapped observation."""
    by_frame: Dict[int, list] = {}
    for tid, obs in tracks.items():
        if tid not in skip:
            for o in obs:
                by_frame.setdefault(o[0], []).append((tid, o[1:]))
    running: Dict[Tuple[int, int], list] = {}   # (a, b) -> [first fid, last fid, observations]
    done: List[dict] = []

    def close(pair, ep):
        if ep[2] >= SWAP_EPISODE_OBS:
            done.append({"a": pair[0], "b": pair[1], "f0": ep[0], "f1": ep[1]})

    for fid in sorted(by_frame):
        here = by_frame[fid]
        touching = {(min(here[i][0], here[j][0]), max(here[i][0], here[j][0]))
                    for i in range(len(here)) for j in range(i + 1, len(here))
                    if _cover(here[i][1], here[j][1]) >= SWAP_COVER}
        for pair in touching:
            ep = running.get(pair)
            if ep is not None and fid - ep[1] <= 2 * stride:
                ep[1], ep[2] = fid, ep[2] + 1
            else:
                if ep is not None:
                    close(pair, ep)
                running[pair] = [fid, fid, 1]
    for pair, ep in running.items():
        close(pair, ep)
    return sorted(done, key=lambda e: (e["f0"], e["a"], e["b"]))


def _clusters(episodes: List[dict], gap: float) -> List[dict]:
    """Overlaps that share a track and happen close together belong to one knot of people: {tracks, f0, f1}."""
    groups: List[dict] = []
    for ep in episodes:
        mine = {"tracks": {ep["a"], ep["b"]}, "f0": ep["f0"], "f1": ep["f1"]}
        for g in [g for g in groups if g["tracks"] & mine["tracks"] and g["f0"] <= mine["f1"] + gap and mine["f0"] <= g["f1"] + gap]:
            mine = {"tracks": mine["tracks"] | g["tracks"], "f0": min(mine["f0"], g["f0"]), "f1": max(mine["f1"], g["f1"])}
            groups.remove(g)
        groups.append(mine)
    return groups


def _velocity_over(obs: list, lo: float, hi: float, fps: float) -> Optional[np.ndarray]:
    rows = [o for o in obs if lo <= o[0] <= hi]
    if len(rows) < 3 or (rows[-1][0] - rows[0][0]) / fps < 0.3:
        return None
    t = np.array([(o[0] - rows[0][0]) / fps for o in rows])
    return np.array([np.polyfit(t, [(o[1] + o[3]) / 2.0 for o in rows], 1)[0],
                     np.polyfit(t, [(o[2] + o[4]) / 2.0 for o in rows], 1)[0]])


def _around(obs: list, samples: list, f0: float, f1: float, fps: float, stride: int) -> Optional[dict]:
    """A track just before the frame f0 and just after f1: where, how fast, how tall and in what colours. None when either side is too short."""
    win = max(SWAP_WINDOW_SEC * fps, (SWAP_MIN_OBS + 1) * stride)   # long enough to hold a few observations at any frame rate
    before = [o for o in obs if f0 - win <= o[0] < f0]
    after = [o for o in obs if f1 < o[0] <= f1 + win]
    if len(before) < SWAP_MIN_OBS or len(after) < SWAP_MIN_OBS:
        return None
    cwin = SWAP_COLOUR_SEC * fps
    cb = [s for s in samples if f0 - cwin <= s[0] <= f0][-4:]
    ca = [s for s in samples if f1 <= s[0] <= f1 + cwin][:4]
    return {
        "last": before[-1], "first": after[0], "v_before": _velocity_over(obs, f0 - win, f0, fps),
        "v_after": _velocity_over(obs, f1, f1 + win, fps), "height": float(np.median([o[4] - o[2] for o in before + after])),
        "colours_before": _mean_signature(cb) if len(cb) >= MIN_PIECE_SAMPLES else (None, None),
        "colours_after": _mean_signature(ca) if len(ca) >= MIN_PIECE_SAMPLES else (None, None),
    }


def _centre(o: Sequence[float]) -> np.ndarray:
    return np.array([(o[1] + o[3]) / 2.0, (o[2] + o[4]) / 2.0])


def _same_person_cost(x: dict, y: dict, fps: float) -> Tuple[float, Optional[float]]:
    """
    Cost of "the person x was before the overlap is the person y is after it", and the colour match used (None
    when either side has no colours, in which case a middling match is assumed, the same for every pairing).
    Position: how far y starts from where x was heading (and the other way round), in body heights; velocity:
    how much their walking changed; colours: how different they look.
    """
    gap = (y["first"][0] - x["last"][0]) / fps
    height = (x["height"] + y["height"]) / 2.0
    ahead = _centre(x["last"]) + (x["v_before"] if x["v_before"] is not None else 0.0) * gap
    behind = _centre(y["first"]) - (y["v_after"] if y["v_after"] is not None else 0.0) * gap
    position = (np.linalg.norm(_centre(y["first"]) - ahead) + np.linalg.norm(_centre(x["last"]) - behind)) / (2.0 * height)
    turn = 0.0
    if x["v_before"] is not None and y["v_after"] is not None:
        turn = float(np.linalg.norm(x["v_before"] - y["v_after"])) / height
    match = colour_match(*x["colours_before"], *y["colours_after"])
    return float(position + W_VELOCITY * turn + W_APPEARANCE * (1.0 - (SWAP_NEUTRAL if match is None else match))), match


def resolve_swaps(tracks: Dict[int, list], signatures: Dict[int, list], fps: float, stride: int, fixtures: set):
    """
    Undo the swaps a tracker makes when people walk past each other or stand in a knot. For every knot of
    overlapping people, the people who carry on afterwards are matched with the people who were there before
    (colours, movement) and compared with what the tracker did: it is changed only when the other pairing is
    clearly better (SWAP_MARGIN), and then the pieces are joined crosswise: each swap (people trading places) is
    judged on its own, and nobody is left in pieces. Only a knot in which everyone can be judged is touched: with
    one person unaccounted for, a pairing of the others can be wrong, so the tracker's stands. Returns the pieces {piece id: observations}, their colour samples, the tracker id
    each came from, the crosswise joins [(piece, piece, evidence)] and a record of each change.
    """
    tracks = {t: sorted(o) for t, o in tracks.items()}
    cut_at: Dict[int, List[float]] = {}
    moves: List[Tuple[int, int, float, dict]] = []   # (before track, after track, frame, evidence)
    log: List[dict] = []
    for knot in _clusters(overlap_episodes(tracks, stride, fixtures), SWAP_GAP_SEC * fps):
        state = {t: _around(tracks[t], signatures.get(t, []), knot["f0"], knot["f1"], fps, stride) for t in sorted(knot["tracks"])}
        ids = [t for t, s in state.items() if s is not None]
        if len(ids) < 2 or len(ids) < len(state):
            continue   # a person in the knot who cannot be judged may be the real match of someone else: leave the knot alone
        table = [[_same_person_cost(state[i], state[j], fps) for j in ids] for i in ids]
        cost = np.array([[c for c, _ in row] for row in table])
        rows, cols = linear_sum_assignment(cost)
        after = dict(zip(rows.tolist(), cols.tolist()))
        mid = (knot["f0"] + knot["f1"]) / 2.0
        seen: set = set()
        for start in sorted(after):
            cycle = []      # the people who would trade places with each other (a swap of two, or a longer ring)
            r = start
            while r not in seen and after[r] != r:
                seen.add(r)
                cycle.append(r)
                r = after[r]
            # each swap stands or falls on its own: a strong one must not carry a weak one with it
            gain = sum(cost[r, r] - cost[r, after[r]] for r in cycle)
            if len(cycle) < 2 or gain < SWAP_MARGIN:
                continue
            for r in cycle:
                moves.append((ids[r], ids[after[r]], mid, {"gain": gain, "match": table[r][after[r]][1]}))
                cut_at.setdefault(ids[r], []).append(mid)
            log.append({"tracks": sorted(ids[r] for r in cycle), "frame": int(mid), "time_s": round(mid / fps, 2),
                        "gain": round(float(gain), 2), "colours": any(table[r][after[r]][1] is not None for r in cycle)})
    pieces: Dict[int, list] = {}
    samples: Dict[int, list] = {}
    origin: Dict[int, int] = {}
    pid_of: Dict[Tuple[int, int], int] = {}
    next_id = max(tracks, default=0) + 1
    for tid in sorted(tracks):
        edges = [-math.inf, *sorted(set(cut_at.get(tid, []))), math.inf]
        for k, (lo, hi) in enumerate(zip(edges, edges[1:])):
            obs = [o for o in tracks[tid] if lo < o[0] <= hi]
            if not obs:
                continue
            pid = tid if k == 0 else next_id
            next_id += 0 if k == 0 else 1
            pieces[pid], origin[pid], pid_of[(tid, k)] = obs, tid, pid
            samples[pid] = [s for s in signatures.get(tid, []) if lo < s[0] <= hi]
    joins = []
    for before, after, mid, evidence in moves:
        a = pid_of.get((before, sorted(set(cut_at[before])).index(mid)))
        b = pid_of.get((after, sorted(set(cut_at[after])).index(mid) + 1))
        if a is not None and b is not None:
            joins.append((a, b, evidence))
    return pieces, samples, origin, joins, log


# ── Step 3: join pieces into visitors ─────────────────────────
VIDEO_EDGE_SEC = 1.0             # a piece starting this soon after the video begins (or ending this long before it ends) was not lost
MIN_EDGE_PX = 3
MIN_DIRECTION_PX = 0.3           # displacements shorter than this many body heights say nothing about direction


def _kind(row: Sequence[float], frame: Tuple[int, int], doors: list) -> Tuple[str, Optional[int]]:
    """Where a piece starts or ends: at the picture's edge, at a shop's door (the nearest one), or midway (anywhere else)."""
    _, x1, y1, x2, y2 = row
    body = y2 - y1
    margin = max(MIN_EDGE_PX, EDGE_BODY * body)
    if x1 <= margin or y1 <= margin or x2 >= frame[0] - margin or y2 >= frame[1] - margin:
        return "edge", None
    feet = ((x1 + x2) / 2.0, y2)
    near = [(places_mod._distance_to_segment(door["a"], door["b"], feet), k) for k, door in enumerate(doors)]
    near = [d for d in near if d[0] <= DOOR_BODY * body]
    return ("door", min(near)[1]) if near else ("midway", None)


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def _motion_ratio(a: Piece, b: Piece, gap: float) -> float:
    """How far b starts from where a was heading (and a ended from where b came from), as a share of what is allowed."""
    step = min(gap, PREDICT_SEC)
    errors = []
    if a.v_end is not None:
        errors.append(np.linalg.norm(b.centre[0] - (a.centre[-1] + a.v_end * step)) / a.h_end)
    if b.v_start is not None:
        errors.append(np.linalg.norm(a.centre[-1] - (b.centre[0] - b.v_start * step)) / b.h_start)
    if not errors:
        errors.append(np.linalg.norm(b.centre[0] - a.centre[-1]) / a.h_end)
    return float(np.mean(errors)) / (TOL_BODY + TOL_PER_SEC * gap)


def _direction_cost(a: Piece, b: Piece) -> float:
    """0 when b carries on the way a was walking, 1 when it turns right round. 0 when either is standing still."""
    costs = []
    d = b.centre[0] - a.centre[-1]
    if a.v_end is not None and np.linalg.norm(a.v_end) >= MOVING * a.h_end and np.linalg.norm(d) >= MIN_DIRECTION_PX * a.h_end:
        costs.append((1.0 - _cos(a.v_end, d)) / 2.0)
    if (a.v_end is not None and b.v_start is not None and np.linalg.norm(a.v_end) >= MOVING * a.h_end
            and np.linalg.norm(b.v_start) >= MOVING * b.h_start):
        costs.append((1.0 - _cos(a.v_end, b.v_start)) / 2.0)
    return float(np.mean(costs)) if costs else 0.0


def link_evidence(a: Piece, b: Piece, fps: float, memory_sec: float, ends: tuple, starts: tuple,
                  assumed: Optional[float] = None) -> Optional[dict]:
    """
    What there is for "b is the same person as a, a little later", or None when it cannot be.
    ends / starts: (kind, door) of where a ends and where b starts. Two ways to link: b picks up from where a
    was heading within the memory (kind "gap"), or both are at the same shop door, however long after (kind "door").
    The colours must match over both pieces as a whole and where one ends and the other starts (a track that
    changed person near its end must not be joined on the strength of how it looked before).
    assumed: use this colour match instead of the real one (for a piece that has no colours, as a rival).
    """
    gap = (b.f0 - a.f1) / fps
    same_door = ends[0] == "door" and starts[0] == "door" and ends[1] == starts[1]
    if gap <= 0 or gap > (DOOR_RETURN_SEC if same_door else memory_sec):
        return None
    if assumed is not None:
        app = assumed
    else:
        app = colour_match(a.shirt, a.trousers, b.shirt, b.trousers)
        junction = colour_match(*a.tail, *b.head)
        if app is None or app < MIN_SIM or (junction is not None and junction < MIN_SIM):
            return None
        app = app if junction is None else min(app, junction)
    best = None
    if gap <= memory_sec and abs(math.log(b.h_start / a.h_end)) <= SIZE_LOG + SIZE_LOG_PER_SEC * gap:
        ratio = _motion_ratio(a, b, gap)
        if ratio <= MAX_RATIO:
            direction = _direction_cost(a, b)
            cost = (W_APPEARANCE * (1.0 - app) + W_MOTION * ratio + W_GAP * gap / memory_sec
                    + W_DIRECTION * direction)
            best = {"kind": "gap", "cost": cost, "motion": ratio, "direction": direction}
    if same_door:
        cost = W_APPEARANCE * (1.0 - app) + W_DOOR + W_GAP * min(1.0, gap / DOOR_RETURN_SEC)
        if best is None or cost < best["cost"]:
            best = {"kind": "door", "cost": cost, "motion": None, "direction": None}
    if best is None:
        return None
    return {**best, "gap_s": gap, "appearance": app}


def _leave_cost(kind: str, at_video_edge: bool) -> float:
    return LEAVE_PLAUSIBLE if kind != "midway" or at_video_edge else LEAVE_MIDWAY


def _best_total(gains: np.ndarray) -> float:
    """The most gain one-to-one pairing can collect from a small table (a zero means no pairing)."""
    if gains.size == 0:
        return 0.0
    r, c = linear_sum_assignment(gains, maximize=True)
    return float(gains[r, c].sum())


def _best_pairs(gain: Dict[Tuple[int, int], float]) -> List[Tuple[int, int]]:
    """
    The pairing of ends with starts that collects the most gain, as a sparse problem: every end may take one
    of its candidate starts, or none. gain[(i, j)] > 0 is what pairing i with j saves over leaving both unpaired.
    """
    ends = sorted({i for i, _ in gain})
    starts = sorted({j for _, j in gain})
    row, col = {i: k for k, i in enumerate(ends)}, {j: k for k, j in enumerate(starts)}
    top = max(gain.values()) + 1.0   # weights must be above zero to count as edges; each end is matched once, so a shift changes nothing
    r_idx = [row[i] for i, _ in gain] + list(range(len(ends)))
    c_idx = [col[j] for _, j in gain] + [len(starts) + k for k in range(len(ends))]   # every end also has a column of its own: "none"
    weights = [top - g for g in gain.values()] + [top] * len(ends)
    matrix = csr_matrix((weights, (r_idx, c_idx)), shape=(len(ends), len(starts) + len(ends)))
    rows, cols = min_weight_full_bipartite_matching(matrix)
    return [(ends[r], starts[c]) for r, c in zip(rows, cols) if c < len(starts)]


def _local_margin(i: int, j: int, gain: Dict[Tuple[int, int], float], into: Dict[int, List[int]], out: Dict[int, List[int]]) -> float:
    """
    How much the gain drops when i is not paired with j, among the pieces around them: the ends that could take j
    and the starts that i could take, and (a second step out) whoever else could take or be taken by those, since
    giving i another start may displace a pair that was fine. Small: somebody else could just as well be this person.
    """
    near_ends = {i, *into[j]}
    near_starts = {j, *out[i]}
    ends = near_ends | {r for c in near_starts for r in into[c]}
    starts = near_starts | {c for r in near_ends for c in out[r]}
    order_e = [i] + sorted(ends - {i})
    order_s = [j] + sorted(starts - {j})
    table = np.zeros((len(order_e), len(order_s)))
    for r, end in enumerate(order_e):
        for c, start in enumerate(order_s):
            table[r, c] = gain.get((end, start), 0.0)
    without = table.copy()
    without[0, 0] = 0.0
    return table[0, 0] + _best_total(table[1:, 1:]) - _best_total(without)


def link_pieces(pieces: List[Piece], fps: float, memory_sec: float, frame: Tuple[int, int], doors: list,
                last_fid: float, has_next: frozenset = frozenset(), has_previous: frozenset = frozenset()) -> List[dict]:
    """
    Decide which pieces are one person: the best one-to-one pairing of piece ends with piece starts, by cost, in
    which leaving a piece unpaired is cheap where a person really leaves (picture edge, shop door, video edge) and
    dear in the middle of the walkway, where they probably did not. Each pair is then rated: confirmed only when
    the colours, the movement and the margin are all clear. The margin is how much the pairing is worth over the
    next best arrangement of the pieces that compete for these two: small means somebody else could just as well
    be this person. A piece without colours also counts as a rival (assumed to match as well as the bar), so a
    join is not confirmed while an equally good piece that cannot be recognised is there.
    has_next / has_previous: pieces whose end (start) is already joined to another piece by a swap.
    """
    n = len(pieces)
    ends = [_kind(p.obs[-1], frame, doors) for p in pieces]
    starts = [_kind(p.obs[0], frame, doors) for p in pieces]
    leave_end = [_leave_cost(ends[i][0], pieces[i].f1 >= last_fid - VIDEO_EDGE_SEC * fps) for i in range(n)]
    leave_start = [_leave_cost(starts[j][0], pieces[j].f0 <= VIDEO_EDGE_SEC * fps) for j in range(n)]

    # Which starts could follow each end: those within the memory, and those at the same shop door however long after
    by_start = sorted(range(n), key=lambda k: pieces[k].f0)
    start_frames = [pieces[k].f0 for k in by_start]
    at_door: Dict[int, List[int]] = {}
    for k in by_start:
        if starts[k][0] == "door":
            at_door.setdefault(starts[k][1], []).append(k)
    door_frames = {d: [pieces[k].f0 for k in ks] for d, ks in at_door.items()}

    def followers(i: int) -> List[int]:
        a = pieces[i]
        found = by_start[bisect_right(start_frames, a.f1):bisect_right(start_frames, a.f1 + memory_sec * fps)]
        if ends[i][0] == "door" and ends[i][1] in at_door:
            ks, fs = at_door[ends[i][1]], door_frames[ends[i][1]]
            found = found + ks[bisect_right(fs, a.f1):bisect_right(fs, a.f1 + DOOR_RETURN_SEC * fps)]
        return [j for j in dict.fromkeys(found) if j != i]

    candidates: Dict[Tuple[int, int], dict] = {}
    for i, a in enumerate(pieces):
        if a.pid in has_next:
            continue
        for j in followers(i):
            if pieces[j].pid not in has_previous:
                ev = link_evidence(a, pieces[j], fps, memory_sec, ends[i], starts[j])
                if ev is not None:
                    candidates[(i, j)] = ev
    # each end keeps its cheapest few followers and each start its cheapest few predecessors: the rest cannot change the answer
    keep: set = set()
    for side in (0, 1):
        groups: Dict[int, list] = {}
        for pair, ev in candidates.items():
            groups.setdefault(pair[side], []).append((ev["cost"], pair))
        for rows in groups.values():
            keep.update(pair for _, pair in sorted(rows)[:KEEP_BEST])
    gain = {pair: leave_end[pair[0]] + leave_start[pair[1]] - candidates[pair]["cost"] for pair in keep}
    gain = {pair: g for pair, g in gain.items() if g > 0}
    if not gain:
        return []
    out: Dict[int, List[int]] = {}
    into: Dict[int, List[int]] = {}
    for i, j in gain:
        out.setdefault(i, []).append(j)
        into.setdefault(j, []).append(i)

    colourless = [k for k in range(n) if pieces[k].shirt is None]

    def rival(cost_of, others) -> float:
        costs = [ev["cost"] for ev in (cost_of(k) for k in others) if ev is not None]
        return min(costs, default=math.inf)

    links = []
    for i, j in _best_pairs(gain):
        ev = candidates[(i, j)]
        a, b = pieces[i], pieces[j]
        margin = _local_margin(i, j, gain, into, out)
        margin = min(margin,   # a piece with no colours that fits as well as a recognised one is a rival too
                     rival(lambda k: link_evidence(a, pieces[k], fps, memory_sec, ends[i], starts[k], ASSUMED_MATCH)
                           if k != j and pieces[k].pid not in has_previous else None, colourless) - ev["cost"],
                     rival(lambda k: link_evidence(pieces[k], b, fps, memory_sec, ends[k], starts[j], ASSUMED_MATCH)
                           if k != i and pieces[k].pid not in has_next else None, colourless) - ev["cost"])
        door = ev["kind"] == "door"
        confirmed = (ev["appearance"] >= (CONFIRM_DOOR_SIM if door else CONFIRM_SIM)
                     and (door or ev["motion"] <= CONFIRM_RATIO) and margin >= CONFIRM_MARGIN)
        links.append({
            "a": a.pid, "b": b.pid, "kind": ev["kind"], "level": CONFIRMED if confirmed else CANDIDATE,
            "gap_s": round(ev["gap_s"], 2), "appearance": round(ev["appearance"], 3),
            "motion": None if ev["motion"] is None else round(ev["motion"], 2),
            "margin": round(margin, 2), "cost": round(ev["cost"], 2), "from": ends[i][0], "to": starts[j][0],
        })
    return sorted(links, key=lambda l: (l["a"], l["b"]))


def _rgb_hex(rows: list) -> Optional[str]:
    rows = [r for r in rows if r is not None]
    if not rows:
        return None
    r, g, b = (int(v) for v in np.median(rows, axis=0))
    return f"#{r:02x}{g:02x}{b:02x}"


def resolve(data: dict, shops_px: list, memory_sec: float = MEMORY_SEC[0], swaps: bool = True) -> dict:
    """
    Visitors for one video. data: width, height, fps, stride, last_fid, tracks, signatures (see processor.load_tracks);
    shops_px: shops as places.to_pixels gives them (their doors tell where a person may disappear and return).
    Returns the pieces (tracks after undoing swaps), person_of {piece id: visitor number}, the visitors, every link
    (the swaps undone are links too) and a record of each knot that was changed.
    """
    fps, stride, last_fid = data["fps"], data["stride"], data["last_fid"]
    frame = (data["width"], data["height"])
    tracks = {t: sorted(o) for t, o in data["tracks"].items()}
    signatures = data.get("signatures", {})
    fixtures = {t for t, o in tracks.items() if len(o) >= 2 and places_mod.is_fixture(o, fps, last_fid)}
    cuts: List[dict] = []
    joins: list = []
    if swaps:
        cut_obs, samples, origin, joins, cuts = resolve_swaps(tracks, signatures, fps, stride, fixtures)
    else:
        cut_obs, samples, origin = tracks, {t: signatures.get(t, []) for t in tracks}, {t: t for t in tracks}
    pieces = {pid: Piece(pid, origin[pid], obs, samples.get(pid, []), fps, origin[pid] in fixtures)
              for pid, obs in cut_obs.items()}
    linkable = [p for p in pieces.values() if not p.fixture and len(p.obs) >= MIN_LINK_OBS]
    links = [{
        "a": a, "b": b, "kind": "swap", "level": CONFIRMED, "gap_s": round((pieces[b].f0 - pieces[a].f1) / fps, 2),
        "appearance": None if ev["match"] is None else round(ev["match"], 3), "motion": None,
        "margin": round(ev["gain"], 2), "cost": None, "from": "midway", "to": "midway",
    } for a, b, ev in joins]
    if linkable and len(linkable) <= MAX_LINK_PIECES:
        links += link_pieces(linkable, fps, memory_sec, frame, shops_px, last_fid,
                             frozenset(a for a, _, _ in joins), frozenset(b for _, b, _ in joins))

    # visitors: the confirmed links chain pieces together (each piece has at most one before and one after)
    root = {pid: pid for pid in pieces}

    def find(x):
        while root[x] != x:
            root[x] = root[root[x]]
            x = root[x]
        return x

    for l in links:
        if l["level"] == CONFIRMED:
            root[find(l["b"])] = find(l["a"])
    groups: Dict[int, List[Piece]] = {}
    for p in pieces.values():
        groups.setdefault(find(p.pid), []).append(p)
    counted = sorted((g for g in groups.values() if not g[0].fixture and any(len(p.obs) >= 2 for p in g)),
                     key=lambda g: min(p.f0 for p in g))
    rest = sorted((g for g in groups.values() if g not in counted), key=lambda g: min(p.f0 for p in g))
    person_of: Dict[int, int] = {}
    for number, group in enumerate(counted + rest, start=1):
        for p in group:
            person_of[p.pid] = number
    doubtful = {l["a"] for l in links if l["level"] == CANDIDATE} | {l["b"] for l in links if l["level"] == CANDIDATE}
    visitors = []
    for group in counted:
        number = person_of[group[0].pid]
        group.sort(key=lambda p: p.f0)
        rows = [s for p in group for s in p.samples]
        mine = {p.pid for p in group}
        visitors.append({
            "id": number, "label": label(number),
            "tracks": sorted({p.tid for p in group}), "pieces": [p.pid for p in group],
            "first_s": round(group[0].f0 / fps, 2), "last_s": round(max(p.f1 for p in group) / fps, 2),
            "seen_s": round(sum(p.seconds() for p in group), 1),
            "shirt": _rgb_hex([s[3] for s in rows]), "trousers": _rgb_hex([s[4] for s in rows]),
            "samples": len(rows),
            "joined": len(group) - 1,
            "uncertain": any(p.pid in doubtful for p in group),
            "links": [l for l in links if l["a"] in mine or l["b"] in mine],   # what each join (or doubt) was based on
        })
    return {
        "pieces": cut_obs, "origin": origin, "person_of": person_of, "visitors": visitors,
        "links": links, "cuts": cuts, "fixtures": sorted(fixtures),
    }
