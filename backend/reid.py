"""
reid.py
=======
Decides when a new tracker ID is the same person as an earlier one, so someone
who leaves the frame and comes back is counted once.

The appearance signature is built from colour histograms of the hair, upper body
and lower body (no model download). It is intentionally conservative: a person
is only merged into an earlier identity when

  * their tracks never overlap in time (one person cannot be in two places),
  * the colour similarity clears `threshold`, and
  * the best match beats the runner-up by `margin` (otherwise it is ambiguous).

Weaker than a trained re-ID network: people in similar clothing can be mixed up,
and strong lighting changes can split one person in two. Every decision is kept
in `Gallery.log` so it can be audited. `embed` is the only part that would
change if a trained model is plugged in later.
"""

from typing import Dict, List, Optional

import cv2
import numpy as np

# region -> (y0, y1, x0, x1) as fractions of the person box
REGIONS = {
    "hair":  (0.02, 0.11, 0.30, 0.70),
    "upper": (0.22, 0.50, 0.20, 0.80),
    "lower": (0.55, 0.85, 0.25, 0.75),
}
WEIGHTS = {"hair": 0.2, "upper": 0.45, "lower": 0.35}
BINS = (12, 3, 4)  # hue, saturation, value


def _hist(crop: np.ndarray) -> Optional[np.ndarray]:
    if crop.shape[0] < 6 or crop.shape[1] < 6:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h = cv2.calcHist([hsv], [0, 1, 2], None, list(BINS), [0, 180, 0, 256, 0, 256]).flatten()
    s = h.sum()
    return h / s if s > 0 else None


def embed(frame: np.ndarray, box) -> Dict[str, np.ndarray]:
    """Colour signature of one person: {region: normalised histogram}. Regions that cannot be read are omitted."""
    x1, y1, x2, y2 = box
    h, w = y2 - y1, x2 - x1
    out = {}
    clipped_bottom = y2 >= frame.shape[0] - 2   # legs cut off by the frame edge
    for name, (a, b, c, d) in REGIONS.items():
        if name == "lower" and clipped_bottom:
            continue
        crop = frame[int(y1 + a * h):int(y1 + b * h), int(x1 + c * w):int(x1 + d * w)]
        hist = _hist(crop)
        if hist is not None:
            out[name] = hist
    return out


def similarity(a: Dict[str, np.ndarray], b: Dict[str, np.ndarray]) -> float:
    """Weighted Bhattacharyya coefficient over the regions both signatures have (1.0 = identical colours)."""
    num = den = 0.0
    for name, w in WEIGHTS.items():
        if name in a and name in b:
            num += w * float(np.sqrt(a[name] * b[name]).sum())
            den += w
    return num / den if den >= 0.5 else 0.0   # need at least the upper body plus one more region


def _near_in_space(last_box, first_box) -> bool:
    """True when a track starts about where another one ended: centres close, similar size."""
    ax1, ay1, ax2, ay2 = last_box
    bx1, by1, bx2, by2 = first_box
    aw, ah, bw, bh = ax2 - ax1, ay2 - ay1, bx2 - bx1, by2 - by1
    if min(aw, ah, bw, bh) <= 0:
        return False
    dist = np.hypot((ax1 + ax2 - bx1 - bx2) / 2.0, (ay1 + ay2 - by1 - by2) / 2.0)
    size_ratio = (bw * bh) / (aw * ah)
    return dist <= 0.5 * max(aw, bw) and 0.5 <= size_ratio <= 2.0


class Gallery:
    def __init__(self, threshold: float = 0.88, margin: float = 0.02, min_samples: int = 5,
                 stitch_threshold: float = 0.76, stitch_gap: int = 45):
        self.threshold = threshold
        self.margin = margin
        self.min_samples = min_samples
        # A track that starts within `stitch_gap` frames of another one ending, at about the
        # same place, only needs `stitch_threshold`: the tracker most likely just lost the
        # ID in a crowd and handed out a new one for the same person.
        self.stitch_threshold = stitch_threshold
        self.stitch_gap = stitch_gap
        self.tracks: Dict[int, dict] = {}        # tid -> {sum, n, first, last, samples}
        self.members: Dict[int, List[int]] = {}  # identity id -> tracker ids
        self.assigned: Dict[int, int] = {}       # tid -> identity id
        self.log: List[dict] = []

    # ── input ────────────────────────────────────────────
    def seen(self, tid: int, fid: int, box=None):
        t = self.tracks.setdefault(tid, {"sum": {}, "n": {}, "first": fid, "last": fid, "samples": 0,
                                         "first_box": box, "last_box": box})
        t["last"] = fid
        if box is not None:
            t["last_box"] = box
            if t.get("first_box") is None:
                t["first_box"] = box

    def add(self, tid: int, fid: int, sig: Dict[str, np.ndarray]):
        self.seen(tid, fid)
        t = self.tracks[tid]
        for name, hist in sig.items():
            t["sum"][name] = t["sum"].get(name, 0.0) + hist
            t["n"][name] = t["n"].get(name, 0) + 1
        t["samples"] += 1

    # ── lookup ───────────────────────────────────────────
    def pid(self, tid: int) -> int:
        """Identity of a track; a track not yet matched stands for itself."""
        return self.assigned.get(tid, tid)

    def _mean(self, tids: List[int]) -> Dict[str, np.ndarray]:
        total, count = {}, {}
        for t in tids:
            tr = self.tracks.get(t)
            if not tr:
                continue
            for name, s in tr["sum"].items():
                total[name] = total.get(name, 0.0) + s
                count[name] = count.get(name, 0) + tr["n"][name]
        return {n: total[n] / count[n] for n in total if count[n] > 0}

    def _overlaps(self, tid: int, other: int) -> bool:
        a, b = self.tracks[tid], self.tracks[other]
        return a["first"] <= b["last"] and b["first"] <= a["last"]

    # ── matching ─────────────────────────────────────────
    def try_assign(self, tid: int, active: set):
        """Match a track with enough samples to an earlier identity, or open a new one."""
        t = self.tracks.get(tid)
        if t is None or tid in self.assigned or t["samples"] < self.min_samples:
            return
        mine = self._mean([tid])
        scored = []
        for pid, tids in self.members.items():
            if any(m in active or self._overlaps(tid, m) for m in tids):
                continue   # that person is in view (or was) at the same time as this track
            sim = similarity(mine, self._mean(tids))
            # handover: this track began right after one of the identity's tracks ended, in the same spot
            handover = any(
                0 <= t["first"] - self.tracks[m]["last"] <= self.stitch_gap
                and self.tracks[m].get("last_box") is not None and t.get("first_box") is not None
                and _near_in_space(self.tracks[m]["last_box"], t["first_box"])
                for m in tids if m in self.tracks
            )
            scored.append((sim, pid, handover))
        scored.sort(reverse=True)
        # best candidate that clears the bar that applies to it (a handover needs less colour proof)
        ok = [s for s in scored if s[0] >= (self.stitch_threshold if s[2] else self.threshold)]
        best = ok[0] if ok else (scored[0] if scored else (0.0, None, False))
        second = next((s[0] for s in scored if s[1] != best[1]), 0.0)
        if ok and best[0] - second >= self.margin:
            pid = best[1]
            self.members[pid].append(tid)
            decision = "stitched" if best[2] and best[0] < self.threshold else "merged"
        else:
            pid = tid
            self.members[pid] = [tid]
            decision = "new"
        self.assigned[tid] = pid
        self.log.append({
            "track": tid, "identity": pid, "decision": decision,
            "best_similarity": round(best[0], 3), "runner_up": round(second, 3),
            "first_frame": t["first"],
        })
