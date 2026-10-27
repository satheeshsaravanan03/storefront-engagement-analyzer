"""
processor.py
============
Storefront dwell-time pipeline: YOLOv8n person detection + ByteTrack IDs,
a user-defined rectangular storefront zone, and per-track dwell time
measured in *video time* (frame index / FPS), then classified against
configurable engagement thresholds.

Runs as a background job and reports live progress through the JobStore
shared with the FastAPI main process.
"""

import base64
import csv
import threading
import time
import traceback
from collections import deque
from pathlib import Path
from typing import Dict, Optional

import cv2
import numpy as np


# ── Job Store ─────────────────────────────────────────────────
class JobStore:
    """Thread-safe in-memory store for job state."""

    def __init__(self):
        self._data: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self, job_id: str, data: dict):
        with self._lock:
            self._data[job_id] = data.copy()

    def update(self, job_id: str, updates: dict):
        with self._lock:
            if job_id in self._data:
                self._data[job_id].update(updates)

    def get(self, job_id: str) -> Optional[dict]:
        with self._lock:
            return self._data.get(job_id, {}).copy() if job_id in self._data else None


# ── Engagement classification ─────────────────────────────────
NOT_FLAGGED = "not_flagged"
POTENTIAL   = "potential"
STRONG      = "strong"

# BGR colours used in the annotated video
COLORS = {
    NOT_FLAGGED: (170, 170, 170),
    POTENTIAL:   (0, 190, 255),
    STRONG:      (0, 210, 0),
}


def classify(dwell_sec: float, engage_sec: float, strong_sec: float) -> str:
    """<engage_sec: not flagged | engage_sec..<strong_sec: potential | >=strong_sec: strong."""
    if dwell_sec >= strong_sec:
        return STRONG
    if dwell_sec >= engage_sec:
        return POTENTIAL
    return NOT_FLAGGED


# ── Storefront zone ───────────────────────────────────────────
class RectZone:
    """Axis-aligned rectangle defined by ratios (0-1) of the frame size."""

    def __init__(self, x1, y1, x2, y2, W, H):
        xa, xb = sorted((float(x1), float(x2)))
        ya, yb = sorted((float(y1), float(y2)))
        xa, xb = max(0.0, xa), min(1.0, xb)
        ya, yb = max(0.0, ya), min(1.0, yb)
        if xb - xa < 0.01 or yb - ya < 0.01:
            raise ValueError("Storefront zone is too small")
        self.px1, self.py1 = int(xa * W), int(ya * H)
        self.px2, self.py2 = int(xb * W), int(yb * H)

    def contains(self, x, y) -> bool:
        return self.px1 <= x <= self.px2 and self.py1 <= y <= self.py2

    def draw(self, frame):
        overlay = frame.copy()
        cv2.rectangle(overlay, (self.px1, self.py1), (self.px2, self.py2), (255, 120, 40), -1)
        cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)
        cv2.rectangle(frame, (self.px1, self.py1), (self.px2, self.py2), (255, 120, 40), 2)
        cv2.putText(frame, "STOREFRONT ZONE", (self.px1 + 6, max(18, self.py1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 160, 80), 2)


# ── Dwell tracking ────────────────────────────────────────────
class DwellTracker:
    """
    Accumulates time-in-zone per track ID, using video time.

    Each frame a track's feet point is inside the zone adds one frame
    interval. If a track disappears from the zone for no longer than
    `grace_sec` and comes back (occlusion, detector flicker), the gap is
    bridged so one person is not split into two short visits. Longer
    absences simply are not counted. One record exists per track ID.
    """

    def __init__(self, fps: float, grace_sec: float):
        self.fps = fps
        self.grace = grace_sec
        self.visits: Dict[int, dict] = {}

    def update(self, tid: int, fid: int):
        t = fid / self.fps
        v = self.visits.get(tid)
        if v is None:
            self.visits[tid] = {"entry": t, "exit": t, "dwell": 1.0 / self.fps, "last_fid": fid}
            return
        gap = (fid - v["last_fid"]) / self.fps
        v["dwell"] += gap if gap <= self.grace else 1.0 / self.fps
        v["exit"] = t
        v["last_fid"] = fid

    def dwell(self, tid: int) -> Optional[float]:
        v = self.visits.get(tid)
        return v["dwell"] if v else None


# ── Main processing function ──────────────────────────────────
def process_video_job(
    job_id: str,
    video_path: str,
    job_dir: str,
    config: dict,
    jobs: JobStore,
):
    """
    Pipeline: read -> detect -> track -> zone test -> dwell -> classify -> render -> save.
    Called in a thread pool executor from the async FastAPI handler.
    """
    try:
        from ultralytics import YOLO
        import torch

        # ── Config ──────────────────────────────────────────
        confidence = float(config.get("confidence", 0.40))
        engage_sec = float(config.get("engage_sec", 5))
        strong_sec = float(config.get("strong_sec", 10))
        grace_sec  = float(config.get("grace_sec", 1.5))
        zone_cfg   = config.get("zone")
        if not zone_cfg:
            raise ValueError("No storefront zone provided")
        if strong_sec < engage_sec:
            raise ValueError("strong_sec must be >= engage_sec")
        device = "0" if torch.cuda.is_available() else "cpu"

        # ── Load model ───────────────────────────────────────
        jobs.update(job_id, {"status": "processing", "phase": "loading model"})
        model = YOLO("yolov8n.pt")
        _ = model(np.zeros((640, 640, 3), dtype=np.uint8), verbose=False, device=device)

        # ── Open video ───────────────────────────────────────
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {video_path}")

        W     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        H     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        FPS   = float(cap.get(cv2.CAP_PROP_FPS)) or 25.0
        TOTAL = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        zone = RectZone(zone_cfg["x1"], zone_cfg["y1"], zone_cfg["x2"], zone_cfg["y2"], W, H)
        tracker = DwellTracker(FPS, grace_sec)

        jobs.update(job_id, {
            "total_frames": TOTAL,
            "resolution": f"{W}x{H}",
            "source_fps": FPS,
        })

        # ── Video writer (prefer browser-playable H.264) ─────
        out_path = str(Path(job_dir) / "annotated.mp4")
        writer = None
        for codec in ("avc1", "mp4v"):
            w = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*codec), FPS, (W, H))
            if w.isOpened():
                writer = w
                break
            w.release()
        if writer is None:
            raise RuntimeError("Could not open a video writer")

        fps_buf = deque(maxlen=30)
        fid = 0
        preview_every = max(1, TOTAL // 200) if TOTAL > 0 else 10

        # ── Frame loop ───────────────────────────────────────
        while True:
            t0 = time.time()
            ret, frame = cap.read()
            if not ret:
                break

            try:
                results = model.track(
                    frame, persist=True, classes=[0],
                    conf=confidence, iou=0.45,
                    tracker="bytetrack.yaml",
                    verbose=False, device=device,
                )
            except Exception:
                fid += 1
                continue

            people = []  # (tid, x1, y1, x2, y2, conf)
            r = results[0]
            if r.boxes is not None and r.boxes.id is not None:
                boxes = r.boxes.xyxy.cpu().numpy().astype(int)
                ids   = r.boxes.id.cpu().numpy().astype(int)
                confs = r.boxes.conf.cpu().numpy()
                for box, tid, cf in zip(boxes, ids, confs):
                    x1, y1, x2, y2 = box
                    x1, y1 = max(0, x1), max(0, y1)
                    x2, y2 = min(W - 1, x2), min(H - 1, y2)
                    people.append((int(tid), x1, y1, x2, y2, float(cf)))

            # Zone test on the feet point (bottom-centre of the box)
            in_zone_now = 0
            for tid, x1, y1, x2, y2, _ in people:
                if zone.contains((x1 + x2) // 2, y2):
                    tracker.update(tid, fid)
                    in_zone_now += 1

            counts = {NOT_FLAGGED: 0, POTENTIAL: 0, STRONG: 0}
            for v in tracker.visits.values():
                counts[classify(v["dwell"], engage_sec, strong_sec)] += 1

            fps_buf.append(1.0 / max(time.time() - t0, 1e-6))
            fps = float(np.mean(fps_buf))
            t_video = fid / FPS

            # ── Render ──────────────────────────────────────
            zone.draw(frame)
            for tid, x1, y1, x2, y2, cf in people:
                d = tracker.dwell(tid)
                cat = classify(d, engage_sec, strong_sec) if d is not None else NOT_FLAGGED
                color = COLORS[cat]
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                label = f"#{tid}" if d is None else f"#{tid} {d:.1f}s"
                cv2.putText(frame, label, (x1, max(14, y1 - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

            hud = (f"t={t_video:5.1f}s  in zone: {in_zone_now}  visits: {len(tracker.visits)}  "
                   f"potential: {counts[POTENTIAL]}  strong: {counts[STRONG]}")
            cv2.rectangle(frame, (0, 0), (W, 26), (15, 15, 15), -1)
            cv2.putText(frame, hud, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

            writer.write(frame)

            if fid % preview_every == 0:
                pct = int(fid / TOTAL * 100) if TOTAL > 0 else 0
                pf = cv2.resize(frame, (640, int(640 * H / W)))
                _, jpg = cv2.imencode(".jpg", pf, [cv2.IMWRITE_JPEG_QUALITY, 70])
                jobs.update(job_id, {
                    "progress":         pct,
                    "processed_frames": fid,
                    "fps":              round(fps, 1),
                    "preview_frame":    base64.b64encode(jpg.tobytes()).decode(),
                    "frame_data": {
                        "time_sec":    round(t_video, 1),
                        "in_zone_now": in_zone_now,
                        "visits":      len(tracker.visits),
                        "potential":   counts[POTENTIAL],
                        "strong":      counts[STRONG],
                        "fps":         round(fps, 1),
                    },
                })

            fid += 1

        cap.release()
        writer.release()

        # ── Final results ────────────────────────────────────
        visits = []
        for tid, v in sorted(tracker.visits.items(), key=lambda kv: kv[1]["entry"]):
            visits.append({
                "track_id":  tid,
                "entry_sec": round(v["entry"], 2),
                "exit_sec":  round(v["exit"], 2),
                "dwell_sec": round(v["dwell"], 2),
                "category":  classify(v["dwell"], engage_sec, strong_sec),
            })

        with open(Path(job_dir) / "visits.csv", "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=["track_id", "entry_sec", "exit_sec", "dwell_sec", "category"])
            wr.writeheader()
            wr.writerows(visits)

        jobs.update(job_id, {
            "status":           "done",
            "progress":         100,
            "processed_frames": fid,
            "preview_frame":    None,
            "stats": {
                "duration_sec": round(fid / max(FPS, 1), 1),
                "resolution":   f"{W}x{H}",
                "source_fps":   round(FPS, 1),
                "total_frames": fid,
                "engage_sec":   engage_sec,
                "strong_sec":   strong_sec,
            },
            "visits": visits,
        })

    except Exception as e:
        jobs.update(job_id, {
            "status": "error",
            "error":  f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()[-800:]}",
        })
