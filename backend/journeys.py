"""
journeys.py
===========
Per-shop numbers and cross-shop patterns from the events of places.py (enter, exit, peek, stop).

People are the ids that places.analyze gives (a track id, or the person it was matched to by re-ID).
The overlap tables are built twice: for people who ENTERED a shop, and for people who showed
INTEREST in it (entered or stopped in front).
"""

from collections import Counter, defaultdict
from statistics import mean
from typing import Dict, List


def overlap(sets: Dict[str, set]) -> dict:
    """Which shops each person is in: exact combinations, plus 'in A but not in B' for every pair."""
    names = list(sets)
    people = set().union(*sets.values()) if sets else set()
    combos = defaultdict(list)
    for pid in people:
        combos[tuple(n for n in names if pid in sets[n])].append(pid)
    return {
        "people": len(people),
        "combinations": [
            {"places": list(k), "count": len(v), "person_ids": sorted(v)}
            for k, v in sorted(combos.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        ],
        "a_not_b": {a: {b: len(sets[a] - sets[b]) for b in names if b != a} for a in names},
    }


def inside_times(events: List[dict]) -> List[float]:
    """Seconds between an enter and the next exit of the same person at the same shop, where both were seen."""
    per = defaultdict(list)
    for e in events:
        if e["event"] in ("enter", "exit"):
            per[(e["person_id"], e["place"])].append(e)
    out = []
    for evs in per.values():
        evs.sort(key=lambda e: e["time_s"])
        for i, e in enumerate(evs):
            if e["event"] != "enter":
                continue
            for nxt in evs[i + 1:]:
                if nxt["event"] == "enter":
                    break
                out.append(nxt["time_s"] - e["time_s"])
                break
    return out


def summarize(events: List[dict], front: List[dict], places: List[dict]) -> dict:
    """Numbers per shop, the overlaps between shops, and the order people went through them."""
    names = [p["name"] for p in places]
    has_front = {p["name"]: bool(p["front"]) for p in places}
    by_place = {n: [e for e in events if e["place"] == n] for n in names}

    entered = {n: {e["person_id"] for e in by_place[n] if e["event"] == "enter"} for n in names}
    stopped = {n: {e["person_id"] for e in by_place[n] if e["event"] == "stop"} for n in names}
    in_front = {n: {r["person_id"] for r in front if r["place"] == n} for n in names}
    interested = {n: entered[n] | stopped[n] for n in names}

    rows = []
    for n in names:
        evs = by_place[n]
        entries = sum(1 for e in evs if e["event"] == "enter")
        times = inside_times(evs)
        rows.append({
            "name": n,
            "entered": len(entered[n]),
            "entries": entries,
            "reentries": entries - len(entered[n]),
            "exits": sum(1 for e in evs if e["event"] == "exit"),
            "peeks": sum(1 for e in evs if e["event"] == "peek"),
            "avg_inside_s": round(mean(times), 1) if times else None,
            "has_front": has_front[n],
            "stopped": len(stopped[n]) if has_front[n] else None,
            "passed": len(in_front[n] - stopped[n] - entered[n]) if has_front[n] else None,
            "entered_ids": sorted(entered[n]),
            "stopped_ids": sorted(stopped[n]),
        })

    # the shops each person entered, in the order they went in (a shop entered twice in a row counts once)
    path = defaultdict(list)
    for e in sorted(events, key=lambda e: (e["time_s"], e["person_id"])):
        if e["event"] == "enter" and (not path[e["person_id"]] or path[e["person_id"]][-1] != e["place"]):
            path[e["person_id"]].append(e["place"])
    direct = Counter(pair for seq in path.values() for pair in zip(seq, seq[1:]))
    seqs = defaultdict(list)
    for pid, seq in path.items():
        seqs[tuple(seq)].append(pid)

    return {
        "places": rows,
        "overlap_entered": overlap(entered),
        "overlap_interested": overlap(interested),
        "transitions": {a: {b: direct.get((a, b), 0) for b in names} for a in names},
        "journeys": [
            {"places": list(k), "count": len(v), "person_ids": sorted(v)}
            for k, v in sorted(seqs.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        ],
    }
