"""
idmetrics.py
============
How well do the ids a tracker (or identity.py) gives follow the people somebody labelled by hand?

  score(labelled, ours)  ->  IDF1, ID switches, extra fragments, ids that mix 2+ people, ...

Both are {frame number: [(id, (x1, y1, x2, y2))]}. A box of ours is matched to a labelled box in the same frame
(best one-to-one pairing by overlap, at least `min_iou`); everything else is counted from those matches.
`frames` is the set of frames the analysis looked at: a frame in it where we found nobody counts as a miss.
`load_caviar` reads the hand labels of the CAVIAR clips (the ground truth XML next to each video).
"""

import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from typing import Dict, List, Sequence, Tuple

import numpy as np
from scipy.optimize import linear_sum_assignment

Boxes = Dict[int, List[Tuple[object, Tuple[float, float, float, float]]]]


def load_caviar(xml_path: str) -> Boxes:
    """CAVIAR ground truth: for every labelled frame, each person's id and box (x1, y1, x2, y2)."""
    out: Boxes = {}
    for fr in ET.parse(xml_path).getroot().findall("frame"):
        rows = []
        for ob in fr.iter("object"):
            b = ob.find("box")
            if b is not None:
                xc, yc, w, h = (float(b.get(k)) for k in ("xc", "yc", "w", "h"))
                rows.append((ob.get("id"), (xc - w / 2, yc - h / 2, xc + w / 2, yc + h / 2)))
        out[int(fr.get("number"))] = rows
    return out


def iou(a: Sequence[float], b: Sequence[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def match_frames(labelled: Boxes, ours: Boxes, min_iou: float = 0.4, frames=None) -> Tuple[list, int, int]:
    """
    [(frame, labelled id, our id)] for every matched box, then how many labelled and how many of our boxes were compared.
    frames: the analysed frames to compare (default: those where we have boxes, which ignores frames where we found nobody).
    """
    matches, n_labelled, n_ours = [], 0, 0
    for f in sorted(set(labelled) & (set(ours) if frames is None else set(frames))):
        g, p = labelled[f], ours.get(f, [])
        n_labelled += len(g)
        n_ours += len(p)
        if g and p:
            cost = np.array([[1.0 - iou(gb, pb) for _, pb in p] for _, gb in g])
            for i, j in zip(*linear_sum_assignment(cost)):
                if cost[i, j] <= 1.0 - min_iou:
                    matches.append((f, g[i][0], p[j][0]))
    return matches, n_labelled, n_ours


def score(labelled: Boxes, ours: Boxes, min_iou: float = 0.4, frames=None) -> dict:
    """
    idf1: share of boxes that carry the right id, with every labelled person paired with the one id of ours that
        covers them most (and the other way round).
    id_switches: times a labelled person's id changed from one frame to the next they were matched in.
    fragments: ids beyond one that a labelled person was split over (0 when each has a single id).
    mixed: ids of ours that carried 2+ labelled people (a wrong merge, or a swap the tracker made).
    found: share of the labelled boxes that any box of ours was matched to.
    """
    matches, n_labelled, n_ours = match_frames(labelled, ours, min_iou, frames)
    by_label: Dict[object, list] = defaultdict(list)
    by_ours: Dict[object, set] = defaultdict(set)
    for f, g, p in matches:
        by_label[g].append((f, p))
        by_ours[p].add(g)
    switches = fragments = 0
    for rows in by_label.values():
        rows.sort()
        switches += sum(1 for (_, a), (_, b) in zip(rows, rows[1:]) if a != b)
        fragments += len({p for _, p in rows}) - 1
    gids, pids = sorted(by_label, key=str), sorted(by_ours, key=str)
    idtp = 0.0
    if gids and pids:
        overlap = np.zeros((len(gids), len(pids)))
        for gi, g in enumerate(gids):
            counts = Counter(p for _, p in by_label[g])
            for pj, p in enumerate(pids):
                overlap[gi, pj] = counts.get(p, 0)
        r, c = linear_sum_assignment(-overlap)
        idtp = float(overlap[r, c].sum())
    denominator = 2 * idtp + (n_ours - idtp) + (n_labelled - idtp)
    return {
        "idf1": round(2 * idtp / denominator, 3) if denominator else 0.0,
        "id_switches": switches,
        "fragments": fragments,
        "mixed": sum(1 for s in by_ours.values() if len(s) > 1),
        "ids": len(pids),
        "people": len(gids),
        "found": round(len(matches) / n_labelled, 3) if n_labelled else 0.0,
    }


def boxes_by_frame(tracks: Dict[int, list], id_of) -> Boxes:
    """{track id: [(frame, x1, y1, x2, y2)]} as per-frame boxes carrying id_of(track id)."""
    out: Boxes = defaultdict(list)
    for tid, obs in tracks.items():
        for fid, x1, y1, x2, y2 in obs:
            out[int(fid)].append((id_of(tid), (x1, y1, x2, y2)))
    return out


def link_quality(labelled: Boxes, pieces: Dict[int, list], links: list, min_iou: float = 0.4, frames=None) -> dict:
    """
    Which labelled person each piece follows (the one it overlaps most), and how the confirmed links did:
    right (both pieces follow the same person), wrong (they follow different people), unknown (a piece matched nobody).
    """
    matches, _, _ = match_frames(labelled, boxes_by_frame(pieces, lambda t: t), min_iou, frames)
    votes: Dict[object, Counter] = defaultdict(Counter)
    for _, g, p in matches:
        votes[p][g] += 1
    owner = {p: c.most_common(1)[0][0] for p, c in votes.items()}
    out = {"right": 0, "wrong": 0, "unknown": 0}
    wrong = []
    for l in links:
        if l["level"] != "confirmed":
            continue
        a, b = owner.get(l["a"]), owner.get(l["b"])
        if a is None or b is None:
            out["unknown"] += 1
        elif a == b:
            out["right"] += 1
        else:
            out["wrong"] += 1
            wrong.append((l["a"], l["b"], a, b))
    out["wrong_links"] = wrong
    return out
