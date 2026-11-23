"""
places.py
=========
Shop-level movement from the tracked position of every person in a fixed mall camera.

The user marks each shop on the floor of one frame:

  * a door line (two points) plus one "inside" pin. The pin says which side is in, which way people
    walk into the shop (door middle to pin) and how deep the shop area is (that far from the line)
  * optionally a polygon on the floor in front of the shop

Only the FEET of a person are tested against these marks. A body standing in front of a
shop covers the shop's pixels without being in it; the feet are on the floor and say where
the person really is. When the feet are hidden (a crowd, the frame edge) they are estimated
from the head and from how tall a standing person looks at that row of the picture.

Everything the browser sends is in fractions of the frame (0..1), so it holds at any
resolution. The functions here are pure (no video, no model) so they can be tested alone.

Events, per person and shop:
  enter  the feet cross the door line heading toward the pin and then stay in the shop area for
         `stay_sec`, or the track ends at the door or in the shop area (the person walked in and
         is out of view). Walking on past the shop area, or out of the picture, is not an entry.
  peek   crossed in and straight back out within `stay_sec`: shown, but not counted
  exit   the feet cross the door line heading away from the pin
  stop   at least `stop_sec` standing (nearly) still in one stretch in the front area
"""

import math
from typing import Dict, List, Optional, Tuple

import numpy as np

MAX_PLACES = 8
MAX_FRONT_POINTS = 32
MIN_DOOR_LEN = 0.02       # a door line shorter than this share of the frame is a misclick
MIN_INSIDE_DIST = 0.01    # the inside point must not sit on the door line
MIN_FRONT_AREA = 1e-4     # share of the frame

BAND_BODY = 0.1           # dead band either side of the door line, as a share of the person's height there
MIN_BUFFER_PX = 2.0
END_MARGIN = 0.5          # a track that ends this share of the band past the line counts as having crossed
CONFIRM_OBS = 2           # a new side must hold for this many observations to count as a crossing
ENDS_BODY = 0.5           # a point may be this many body heights beyond either end of the door line...
ENDS_MAX = 0.25           # ...but never more than this share of the door line's length (a door seen end-on is short on screen)
ENTRY_COS = 0.2           # a crossing must head at least this far toward (or away from) the pin: cosine of the angle
DOOR_ZONE_BODY = 1.0      # a track that vanishes counts as going in only within this many body heights of the door...
EDGE_BODY = 0.25          # ...and not within this many body heights of the frame edge (they left the picture)
APPROACH_BANDS = 2.0      # a track that ends heading at the door counts as going in if it ends this many bands short of the line
APPROACH_MOVE = 0.15      # ...having walked at least this share of its height in its last observations
APPROACH_COS = 0.8        # ...and straight toward the pin
VANISH_GAP_SEC = 0.5      # a track that ends this long before the video does has vanished
SLOW_SPEED = 0.3          # body heights per second; below this a person is standing, not walking
SPEED_WINDOW_SEC = 0.5
MAX_GAP_SEC = 1.0         # one observation never stands for more than this much time
MIN_PASS_SEC = 0.5        # time in the front area before someone counts as passing by

STATIC_MIN_SEC = 10.0     # a fixture (mannequin, poster) is seen at least this long...
STATIC_SHARE = 0.9        # ...for this share of the video...
STATIC_MOVE = 0.3         # ...and its feet never move more than this share of its height

MIN_HEIGHT_SAMPLES = 40
MAX_FIT_NOISE = 0.3       # the height fit is dropped when its spread is more than this share of a person's height
UPRIGHT_RATIO = 1.6       # box height / width of a standing, whole person
HIDDEN_RATIO = 0.8        # a box this much shorter than expected has its feet hidden
EDGE_PX = 3


# ── Zones sent by the browser ─────────────────────────────────
def _number(v) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError("Zone coordinates must be numbers")
    try:
        x = float(v)
    except OverflowError:   # an integer too big for a float
        raise ValueError("Zone coordinates must be numbers") from None
    if not math.isfinite(x):
        raise ValueError("Zone coordinates must be numbers")
    return x


def _point(v) -> List[float]:
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise ValueError("A zone point must be [x, y]")
    x, y = _number(v[0]), _number(v[1])
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise ValueError("Zone points must lie inside the frame")
    return [x, y]


def polygon_area(poly) -> float:
    n = len(poly)
    s = sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n))
    return abs(s) / 2.0


def parse_places(raw) -> List[dict]:
    """Check the shops sent by the browser and return them in a clean form. Raises ValueError."""
    if not isinstance(raw, list) or not raw:
        raise ValueError("Mark at least one shop")
    if len(raw) > MAX_PLACES:
        raise ValueError(f"Mark at most {MAX_PLACES} shops")
    places, names = [], set()
    for i, p in enumerate(raw):
        if not isinstance(p, dict):
            raise ValueError("Each shop must be an object")
        name = p.get("name", "")
        if not isinstance(name, str):
            raise ValueError("A shop name must be text")
        name = name.strip()[:40] or f"Shop {i + 1}"
        if name.lower() in names:
            raise ValueError(f"Two shops are called '{name}'")
        names.add(name.lower())

        door = p.get("door")
        if not isinstance(door, (list, tuple)) or len(door) != 2:
            raise ValueError(f"'{name}': draw the door line with two points")
        a, b = _point(door[0]), _point(door[1])
        if math.hypot(b[0] - a[0], b[1] - a[1]) < MIN_DOOR_LEN:
            raise ValueError(f"'{name}': the door line is too short")

        if p.get("inside") is None:
            raise ValueError(f"'{name}': click the inside of the shop")
        inside = _point(p["inside"])
        if abs(line_side(a, b, inside)) < MIN_INSIDE_DIST:
            raise ValueError(f"'{name}': the inside point sits on the door line")

        raw_front = p.get("front") or []
        if not isinstance(raw_front, list) or len(raw_front) > MAX_FRONT_POINTS or 0 < len(raw_front) < 3:
            raise ValueError(f"'{name}': the front area needs 3 to {MAX_FRONT_POINTS} points")
        front = [_point(q) for q in raw_front]
        if front and polygon_area(front) < MIN_FRONT_AREA:
            raise ValueError(f"'{name}': the front area is too small")

        places.append({"id": f"S{i + 1}", "name": name, "door": [a, b], "inside": inside, "front": front})
    return places


# ── Geometry ──────────────────────────────────────────────────
def line_side(a, b, p) -> float:
    """Signed distance of p from the line a-b: one sign on each side of it."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    return (dx * (p[1] - a[1]) - dy * (p[0] - a[0])) / math.hypot(dx, dy)


def line_position(a, b, p) -> float:
    """Where p projects onto the segment a-b: 0 at a, 1 at b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    return ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)


def point_in_polygon(poly, p) -> bool:
    x, y = p
    inside, j = False, len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def to_pixels(places: List[dict], w: int, h: int) -> List[dict]:
    """
    Shops in pixel coordinates: the door line and its length, which sign of line_side is inside, the unit
    vector from the middle of the door toward the pin ("inward"), and the shop area: the door line pushed
    toward the pin by as far as the pin is from the door (a parallelogram the editor shades).
    """
    out = []
    for p in places:
        a = (p["door"][0][0] * w, p["door"][0][1] * h)
        b = (p["door"][1][0] * w, p["door"][1][1] * h)
        pin = (p["inside"][0] * w, p["inside"][1] * h)
        mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        vx, vy = pin[0] - mid[0], pin[1] - mid[1]
        depth = math.hypot(vx, vy)
        out.append({
            "id": p["id"], "name": p["name"], "a": a, "b": b,
            "len": math.hypot(b[0] - a[0], b[1] - a[1]),
            "sign": 1.0 if line_side(a, b, pin) > 0 else -1.0,
            "pin": pin, "inward": (vx / depth, vy / depth),
            "region": [a, b, (b[0] + vx, b[1] + vy), (a[0] + vx, a[1] + vy)],
            "front": [(x * w, y * h) for x, y in p["front"]],
        })
    return out


# ── Feet ──────────────────────────────────────────────────────
def _robust_line(ys: np.ndarray, hs: np.ndarray) -> Tuple[float, float]:
    """Theil-Sen line h = slope * y + offset: the median of the slopes between pairs of points, so up to
    about a quarter of the points can be wrong. A spread-out subsample keeps the pairing cheap."""
    pick = np.linspace(0, len(ys) - 1, min(len(ys), 300)).astype(int)
    y, h = ys[pick], hs[pick]
    dy = y[:, None] - y[None, :]
    dh = h[:, None] - h[None, :]
    far = dy > 1.0
    slope = float(np.median(dh[far] / dy[far])) if far.any() else 0.0
    return slope, float(np.median(h - slope * y))


class HeightModel:
    """How tall a standing person looks at each row of the picture: height = slope * feet_row + offset."""

    def __init__(self, slope: float, offset: float):
        self.slope = slope
        self.offset = offset

    def height_at(self, feet_y: float) -> float:
        return self.slope * feet_y + self.offset

    def feet_from_head(self, head_y: float, scale: float = 1.0) -> float:
        """The row where the feet must be, given the head top: the row that is one body height below it."""
        return (head_y + scale * self.offset) / max(1.0 - scale * self.slope, 0.1)

    @classmethod
    def fit(cls, samples: List[Tuple[float, float]], frame_h: float) -> Optional["HeightModel"]:
        """
        Fit from (feet_row, box_height) of whole standing people. Returns None when the perspective cannot be
        learned from this video (too few people, rows too alike while heights differ, or a noisy fit): a wrong
        model would mark people whose feet are in plain view as hidden, so it is better to estimate nothing.
        """
        if len(samples) < MIN_HEIGHT_SAMPLES:
            return None
        ys = np.array([s[0] for s in samples], dtype=float)
        hs = np.array([s[1] for s in samples], dtype=float)
        flat = cls(0.0, float(np.median(hs)))
        if np.percentile(ys, 90) - np.percentile(ys, 10) < 0.08 * frame_h:
            # everyone stands on about the same rows: one height fits, but only if their heights agree
            # (an overhead camera). In a corridor view this is far and near people squeezed into a few rows.
            return flat if np.percentile(hs, 90) <= 1.4 * np.percentile(hs, 10) else None
        # start from a line that outliers cannot drag (boxes with hidden legs are short), then refit on the good boxes
        slope, offset = _robust_line(ys, hs)
        for _ in range(2):
            res = hs - (slope * ys + offset)
            sigma = max(1.4826 * float(np.median(np.abs(res - np.median(res)))), 1.0)
            # hidden legs make a box shorter than the line, so the low side is trimmed harder
            keep = (res >= -1.5 * sigma) & (res <= 2.5 * sigma)
            if keep.sum() < MIN_HEIGHT_SAMPLES:
                return None
            slope, offset = (float(v) for v in np.polyfit(ys[keep], hs[keep], 1))
        res = hs[keep] - (slope * ys[keep] + offset)
        sigma = 1.4826 * float(np.median(np.abs(res - np.median(res))))
        if not 0.0 <= slope < 0.9 or sigma > MAX_FIT_NOISE * float(np.median(hs[keep])):
            return None
        return cls(slope, offset)


def height_samples(tracks: Dict[int, list], frame_h: float) -> List[Tuple[float, float]]:
    """(feet_row, box_height) of boxes that look like a whole standing person."""
    out = []
    for obs in tracks.values():
        for _, x1, y1, x2, y2 in obs:
            w, h = x2 - x1, y2 - y1
            if w > 0 and h / w >= UPRIGHT_RATIO and y1 >= EDGE_PX and y2 <= frame_h - EDGE_PX and h >= 0.03 * frame_h:
                out.append((float(y2), float(h)))
    return out


def track_feet(obs: list, model: Optional[HeightModel], frame_h: float) -> list:
    """
    Feet of one track as (fid, x, feet_row, estimated, body_height) per observation.
    obs: [(fid, x1, y1, x2, y2)] in time order. The box bottom is used when it can be trusted;
    when it is cut by the frame edge or much shorter than a person at that row should be, the
    feet are placed one body height below the head instead.
    """
    scale = 1.0
    if model is not None:
        ratios = []
        for _, x1, y1, x2, y2 in obs:
            expected = model.height_at(y2)
            if expected > 1 and x2 > x1 and (y2 - y1) / (x2 - x1) >= UPRIGHT_RATIO and y2 < frame_h - EDGE_PX:
                ratios.append((y2 - y1) / expected)
        if len(ratios) >= 5:
            # this person is taller or shorter than usual (a child). Hidden legs make a box short, so the taller
            # boxes of the track show the person's own height
            scale = min(max(float(np.percentile(ratios, 75)), 0.6), 1.25)

    out = []
    for fid, x1, y1, x2, y2 in obs:
        feet, estimated = float(y2), False
        if model is not None:
            expected = model.height_at(y2)
            hidden = y2 >= frame_h - EDGE_PX or (expected > 1 and (y2 - y1) < HIDDEN_RATIO * scale * expected)
            if hidden:
                guess = min(model.feet_from_head(y1, scale), y2 + (y2 - y1))   # never more than one body below the box
                if guess > y2:
                    feet, estimated = float(guess), True
        out.append((fid, (x1 + x2) / 2.0, feet, estimated, max(feet - y1, 1.0)))
    return out


# ── Door line ─────────────────────────────────────────────────
def door_crossings(pts: list, shop: dict) -> List[dict]:
    """
    Times the feet of one track cross a shop's door line:
    [{"dir": "in"|"out", "fid", "i0", "i1", "estimated", "weak"}] (i0: last observation on the old side,
    i1: first on the new side). A band around the line, a tenth of the person's height each side, absorbs
    jitter, a new side has to hold for CONFIRM_OBS observations, and a point well beyond the ends of the
    line (someone walking round it) says nothing about the door.

    People often appear at, or vanish into, a doorway where the shop hides them, so three cases count on less
    evidence. A track that starts on the door line is taken as coming out of the shop. A track that ends with
    its feet clearly past the line, or that ends close to the line after walking straight at it, is taken as
    having crossed; that crossing is marked weak (a lower confidence).
    """
    a, b, sign = shop["a"], shop["b"], shop["sign"]
    bufs = [max(BAND_BODY * p[4], MIN_BUFFER_PX) for p in pts]
    ds = [sign * line_side(a, b, (p[1], p[2])) for p in pts]
    margins = [min(ENDS_BODY * p[4] / shop["len"], ENDS_MAX) for p in pts]
    on_door = [-m <= line_position(a, b, (p[1], p[2])) <= 1.0 + m for p, m in zip(pts, margins)]

    def crossing(old: int, new: int, side: str, last: int, weak: bool = False) -> dict:
        """The crossing between the last observation on the old side and the first on the new one."""
        p0, p1 = pts[old], pts[new]
        # between the two the person may have been in the band, off the ends of the line or unseen; only
        # when every point between is in the band does the distance say when the line was crossed
        clean = all(on_door[j] and abs(ds[j]) < bufs[j] for j in range(old + 1, new))
        gap = ds[old] - ds[new]
        s = min(max(ds[old] / gap, 0.0), 1.0) if clean and gap else 1.0
        return {"dir": side, "fid": p0[0] + s * (p1[0] - p0[0]), "i0": old, "i1": new, "weak": weak,
                "estimated": bool(p0[3] or p1[3] or pts[last][3])}

    out = []
    state = last_old = cand = cand_first = None
    cand_n = 0
    on_line = bool(on_door[0] and abs(ds[0]) < bufs[0])   # first seen on the door line: no side is known yet
    if on_line:
        state, last_old = "in", 0
    for i, d in enumerate(ds):
        side = "in" if d >= bufs[i] else "out" if d <= -bufs[i] else None
        if side is None or not on_door[i]:
            continue
        if on_line and side == "out" and d > -2 * bufs[i]:
            continue   # a first step off the line could be a wobble: it has to be a clear one
        if state is None or side == state:
            state, last_old, cand, cand_n = side, i, None, 0
            on_line = on_line and side != "in"   # seen well inside: the side is known now
            continue
        if side != cand:
            cand, cand_n, cand_first = side, 1, i
        else:
            cand_n += 1
        if cand_n < CONFIRM_OBS:
            continue
        out.append(crossing(last_old, cand_first, side, i))
        state, last_old, cand, cand_n, on_line = side, i, None, 0, False

    reach = (2 if on_line else END_MARGIN) * bufs[-1]
    end = "in" if ds[-1] >= reach else "out" if ds[-1] <= -reach else None
    if state is not None and on_door[-1] and end is not None and end != state:
        # a clear step to the new side that never held for CONFIRM_OBS dates the crossing, not the end of the track
        out.append(crossing(last_old, cand_first if cand == end else len(pts) - 1, end, len(pts) - 1, weak=True))
    elif state == "out" and _approaching(pts, ds, bufs, shop, on_door):
        out.append(crossing(last_old, len(pts) - 1, "in", len(pts) - 1, weak=True))
    return out


def _approaching(pts: list, ds: list, bufs: list, shop: dict, on_door: list) -> bool:
    """A track that ends a little short of the line after walking straight at it: the door hides the person
    before the feet reach the line."""
    n = len(pts)
    if n < 3 or not on_door[-1] or not -APPROACH_BANDS * bufs[-1] <= ds[-1] < 0:
        return False
    first = pts[max(0, n - 8)]
    dx, dy = pts[-1][1] - first[1], pts[-1][2] - first[2]
    moved = math.hypot(dx, dy)
    return moved >= APPROACH_MOVE * pts[-1][4] and (dx * shop["inward"][0] + dy * shop["inward"][1]) / moved >= APPROACH_COS


def _confidence(estimated: bool, reason: str, age_sec: float, weak: bool = False) -> float:
    conf = 1.0
    if estimated:
        conf *= 0.75        # the crossing relied on feet worked out from the head
    if weak:
        conf *= 0.85        # the track ended just after the door line, with little to confirm it
    if reason == "end_of_video":
        conf *= 0.6         # the video ended before we could see them stay or vanish
    if age_sec < 1.0:
        conf *= 0.8         # a track that began just before the door may be a re-labelled person
    return round(conf, 2)


def _heading(pts: list, i0: int, i1: int, inward: tuple) -> float:
    """Cosine of the angle between the way a person walks around a crossing and the way into the shop."""
    lo, hi = pts[max(i0 - 2, 0)], pts[min(i1 + 2, len(pts) - 1)]
    dx, dy = hi[1] - lo[1], hi[2] - lo[2]
    moved = math.hypot(dx, dy)
    return (dx * inward[0] + dy * inward[1]) / moved if moved > 0 else 0.0


def _distance_to_segment(a, b, p) -> float:
    t = min(max(line_position(a, b, p), 0.0), 1.0)
    return math.hypot(p[0] - (a[0] + t * (b[0] - a[0])), p[1] - (a[1] + t * (b[1] - a[1])))


def _seconds_in_region(pts: list, start: int, stop: int, region: list, fps: float, since: float,
                       until: Optional[float]) -> float:
    """
    How long after frame `since` (the crossing) the feet stay in the shop area, from observation `start` to
    observation `stop`. If they leave it, that is up to the last observation inside. If they are in it all the
    way, it is up to frame `until` (the crossing back out) or, with none, the last observation: the same
    clock the peek test uses, so a visit is always a peek or a stay and never neither.
    """
    for k in range(start, stop):
        if not point_in_polygon(region, (pts[k][1], pts[k][2])):
            return 0.0 if k == start else (pts[k - 1][0] - since) / fps
    end = pts[stop - 1][0] if until is None else until
    return (end - since) / fps


def _vanished_at_door(pts: list, shop: dict, frame: tuple) -> bool:
    """Whether a track ended where a person would go into the shop: at the door or in the shop area, and not
    at the edge of the picture (someone who walks out of the frame has not gone into a shop)."""
    _, x, y, _, body = pts[-1]
    margin = max(EDGE_PX, EDGE_BODY * body)
    if x <= margin or x >= frame[0] - margin or y >= frame[1] - margin:
        return False
    return (point_in_polygon(shop["region"], (x, y))
            or _distance_to_segment(shop["a"], shop["b"], (x, y)) <= DOOR_ZONE_BODY * body)


def shop_events(pts: list, shop: dict, fps: float, stay_sec: float, last_fid: float, frame: tuple) -> List[dict]:
    """Enter, peek and exit events of one track at one shop. frame is the picture's (width, height) in pixels."""
    out = []
    crossings = door_crossings(pts, shop)
    first_fid, end_fid = pts[0][0], pts[-1][0]
    skip_out = False   # the way back out of an inward crossing that did not count
    for n, c in enumerate(crossings):
        cos = _heading(pts, c["i0"], c["i1"], shop["inward"])
        age = (c["fid"] - first_fid) / fps
        ev = {"time_s": round(c["fid"] / fps, 2), "frame": int(round(c["fid"])), "duration_s": None,
              "feet_estimated": c["estimated"]}
        if c["dir"] == "out":
            if skip_out:       # the way back from a peek, or from a crossing that did not count
                skip_out = False
            elif cos <= -ENTRY_COS:
                out.append({**ev, "event": "exit", "reason": "",
                            "confidence": _confidence(c["estimated"], "", age, c["weak"])})
            continue

        nxt = crossings[n + 1] if n + 1 < len(crossings) else None
        if cos < ENTRY_COS:   # walking along the door, not toward the shop
            skip_out = nxt is not None
            continue
        inside_sec = ((nxt["fid"] if nxt else end_fid) - c["fid"]) / fps
        if nxt is not None and inside_sec < stay_sec:
            out.append({**ev, "event": "peek", "reason": "back out",
                        "confidence": _confidence(c["estimated"], "", age, c["weak"])})
            skip_out = True
            continue
        stop = nxt["i0"] + 1 if nxt else len(pts)
        if _seconds_in_region(pts, c["i1"], stop, shop["region"], fps, c["fid"], nxt["fid"] if nxt else None) >= stay_sec:
            reason = "stay"
        elif nxt is None and _vanished_at_door(pts, shop, frame):
            reason = "vanish" if last_fid - end_fid >= VANISH_GAP_SEC * fps else "end_of_video"
        else:                 # walked on past the shop area, or out of the picture
            skip_out = nxt is not None
            continue
        out.append({**ev, "event": "enter", "reason": reason,
                    "confidence": _confidence(c["estimated"], reason, age, c["weak"])})
    return out


# ── Front area ────────────────────────────────────────────────
def front_stats(pts: list, shop: dict, fps: float) -> Optional[dict]:
    """Seconds with the feet in the shop's front area, and the longest unbroken stretch of it spent standing still."""
    poly = shop["front"]
    if not poly:
        return None
    front = still = run = 0.0
    run_start = still_start = None
    for j, (fid, x, y, _, body_h) in enumerate(pts):
        slow, dt = False, 0.0
        if point_in_polygon(poly, (x, y)):
            dt = min((pts[j + 1][0] - fid) / fps, MAX_GAP_SEC) if j + 1 < len(pts) else 0.0
            front += dt
            k = j
            while k > 0 and (fid - pts[k][0]) / fps < SPEED_WINDOW_SEC:
                k -= 1
            span = (fid - pts[k][0]) / fps
            slow = span >= SPEED_WINDOW_SEC and math.hypot(x - pts[k][1], y - pts[k][2]) / body_h / span <= SLOW_SPEED
        if not slow:
            run, run_start = 0.0, None   # walking, or out of the area: the stretch is over
            continue
        if run_start is None:
            run_start = fid / fps
        run += dt
        if run > still:
            still, still_start = run, run_start
    return {"front_sec": front, "still_sec": still, "stop_start_s": still_start}


# ── All tracks of a video ─────────────────────────────────────
def is_fixture(obs: list, fps: float, last_fid: float) -> bool:
    """A mannequin or poster the detector takes for a person: there for nearly the whole video and never moves."""
    first, last = obs[0][0], obs[-1][0]
    if (last - first) / fps < STATIC_MIN_SEC or last - first < STATIC_SHARE * last_fid:
        return False
    height = float(np.median([o[4] - o[2] for o in obs]))
    moved = max(np.ptp([(o[1] + o[3]) / 2.0 for o in obs]), np.ptp([o[4] for o in obs]))
    return moved < STATIC_MOVE * height


def analyze(tracks: Dict[int, list], person_of: Dict[int, int], places: List[dict], frame_w: int, frame_h: int,
            fps: float, last_fid: float, stay_sec: float = 2.5, stop_sec: float = 3.0) -> dict:
    """
    Events and front-area time for every person at every shop.
    tracks: {track_id: [(fid, x1, y1, x2, y2)]} in pixels; person_of maps a track to a person (re-ID).
    places: shops as returned by parse_places. Returns the events and the front-area rows (both ready for JSON),
    how much of the work used estimated feet, and the feet of every track (in memory, for drawing the video).
    """
    shops = to_pixels(places, frame_w, frame_h)
    seen = {tid: sorted(obs) for tid, obs in tracks.items() if len(obs) >= 2}
    people = {tid: obs for tid, obs in seen.items() if not is_fixture(obs, fps, last_fid)}
    model = HeightModel.fit(height_samples(people, frame_h), frame_h)
    events: List[dict] = []
    front: Dict[tuple, dict] = {}
    feet: Dict[int, list] = {}
    total = estimated = 0
    for tid, obs in people.items():
        pts = feet[tid] = track_feet(obs, model, frame_h)
        pid = person_of.get(tid, tid)
        total += len(pts)
        estimated += sum(1 for p in pts if p[3])
        for shop in shops:
            for ev in shop_events(pts, shop, fps, stay_sec, last_fid, (frame_w, frame_h)):
                events.append({"person_id": pid, "track_id": tid, "place": shop["name"], **ev})
            st = front_stats(pts, shop, fps)
            if st:
                # time in the area adds up over a person's tracks; standing still is the longest single stretch
                acc = front.setdefault((pid, shop["name"]), {"front_sec": 0.0, "still_sec": 0.0, "stop_start_s": None})
                acc["front_sec"] += st["front_sec"]
                if st["still_sec"] > acc["still_sec"]:
                    acc["still_sec"], acc["stop_start_s"] = st["still_sec"], st["stop_start_s"]

    rows = []
    for (pid, name), st in front.items():
        if st["front_sec"] < MIN_PASS_SEC:
            continue
        rows.append({"person_id": pid, "place": name, "front_sec": round(st["front_sec"], 1),
                     "still_sec": round(st["still_sec"], 1)})
        if st["still_sec"] >= stop_sec:
            events.append({"person_id": pid, "track_id": None, "place": name, "event": "stop",
                           "time_s": round(st["stop_start_s"], 2), "frame": int(round(st["stop_start_s"] * fps)),
                           "duration_s": round(st["still_sec"], 1), "confidence": 1.0, "feet_estimated": False,
                           "reason": ""})
    events.sort(key=lambda e: (e["time_s"], e["person_id"]))
    return {
        "events": events,
        "front": sorted(rows, key=lambda r: (r["place"], r["person_id"])),
        "height_model": None if model is None else {"slope": round(model.slope, 4), "offset": round(model.offset, 2)},
        "estimated_share": round(estimated / total, 3) if total else 0.0,
        "feet": feet,
    }
