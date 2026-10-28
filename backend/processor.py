"""
processor.py
============
Visitor attention pipeline: YOLOv8n-pose person detection + ByteTrack IDs.

Only people who are *near* the camera (it is mounted at the product or
advertisement) and *facing* it (head pose from face keypoints) are counted as
viewers. Everyone else - far away, turned away, just passing - is ignored.
Attention time is measured in *video time* (frame index / FPS), and each
viewer is given a behaviour label from how long they looked.

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


# ── Behaviour classification ──────────────────────────────────
GLANCED = "glanced"   # looked, but briefly
LOOKED  = "looked"    # stopped and looked
ENGAGED = "engaged"   # potential engagement
STRONG  = "strong"    # stronger engagement signal

# BGR colours used in the annotated video
COLORS = {
    GLANCED: (200, 200, 200),
    LOOKED:  (0, 215, 255),
    ENGAGED: (0, 165, 255),
    STRONG:  (0, 210, 0),
}


def classify(attention_sec: float, glance_sec: float, engage_sec: float, strong_sec: float) -> str:
    """<glance_sec: glanced | glance..<engage: looked | engage..<strong: engaged | >=strong: strong."""
    if attention_sec >= strong_sec:
        return STRONG
    if attention_sec >= engage_sec:
        return ENGAGED
    if attention_sec >= glance_sec:
        return LOOKED
    return GLANCED


# ── Head pose ─────────────────────────────────────────────────
# COCO keypoint indices
NOSE, L_EYE, R_EYE = 0, 1, 2


def is_facing(kp: np.ndarray, kc: np.ndarray, kp_conf: float, max_offset: float) -> bool:
    """
    Facing the camera when both eyes and the nose are visible and the nose sits
    close to the midpoint between the eyes. As the head turns the nose slides
    toward one eye (and the far eye drops out), so the offset, measured in
    eye-distances, is a proxy for yaw.
    """
    if kc[NOSE] < kp_conf or kc[L_EYE] < kp_conf or kc[R_EYE] < kp_conf:
        return False
    eye_dist = abs(kp[R_EYE][0] - kp[L_EYE][0])
    if eye_dist < 6:  # head too small for a reliable reading
        return False
    mid_x = (kp[L_EYE][0] + kp[R_EYE][0]) / 2.0
    return abs(kp[NOSE][0] - mid_x) / eye_dist <= max_offset


_FACE_CASCADE = None


def has_frontal_face(frame: np.ndarray, kp: np.ndarray) -> bool:
    """
    Confirm with a real frontal-face detector (OpenCV's bundled Haar cascade) on
    the head region. Pose models sometimes place eye/nose keypoints on the back
    of a head; the cascade only fires for faces turned toward the camera.
    """
    global _FACE_CASCADE
    if _FACE_CASCADE is None:
        _FACE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    eye_dist = abs(kp[R_EYE][0] - kp[L_EYE][0])
    cx = (kp[L_EYE][0] + kp[R_EYE][0]) / 2.0
    cy = (kp[L_EYE][1] + kp[R_EYE][1]) / 2.0 + eye_dist * 0.45
    half = eye_dist * 1.6
    x1, y1 = int(max(cx - half, 0)), int(max(cy - half, 0))
    x2, y2 = int(min(cx + half, frame.shape[1])), int(min(cy + half, frame.shape[0]))
    if x2 - x1 < 24 or y2 - y1 < 24:
        return False
    gray = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    faces = _FACE_CASCADE.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(24, 24))
    return len(faces) > 0


# ── Per-person attention tracking ─────────────────────────────
class AttentionTracker:
    """
    Accumulates presence and attention per track ID, using video time.

    Presence counts frames where the person is near the camera. Attention counts
    frames where they are near *and* facing it. If attention drops for no longer
    than `grace_sec` and resumes (head-pose flicker), the gap is bridged so one
    look is not split into several short ones.
    """

    def __init__(self, fps: float, grace_sec: float):
        self.fps = fps
        self.dt = 1.0 / fps
        self.grace = grace_sec
        self.people: Dict[int, dict] = {}

    def update(self, tid: int, fid: int, near: bool, facing: bool, cx: float, cy: float, h: float):
        if not near:
            return
        t = fid / self.fps
        p = self.people.get(tid)
        if p is None:
            p = self.people[tid] = {
                "first": t, "last": t, "present": 0.0, "attention": 0.0,
                "longest": 0.0, "looks": 0, "seg": 0.0, "last_att_fid": None,
                "prev_c": None, "prev_fid": None, "dist": 0.0, "dist_t": 0.0,
            }
        p["last"] = t
        p["present"] += self.dt

        # movement in box-heights per second (scale-free)
        if p["prev_c"] is not None:
            gap = max(fid - p["prev_fid"], 1) / self.fps
            p["dist"] += np.hypot(cx - p["prev_c"][0], cy - p["prev_c"][1]) / max(h, 1.0)
            p["dist_t"] += gap
        p["prev_c"], p["prev_fid"] = (cx, cy), fid

        if facing:
            la = p["last_att_fid"]
            if la is not None and (fid - la) / self.fps <= self.grace:
                add = (fid - la) / self.fps
                p["seg"] += add
            else:
                add = self.dt
                p["looks"] += 1
                p["seg"] = add
            p["attention"] += add
            p["longest"] = max(p["longest"], p["seg"])
            p["last_att_fid"] = fid

    def attention(self, tid: int) -> float:
        p = self.people.get(tid)
        return p["attention"] if p else 0.0

    @staticmethod
    def speed(p: dict) -> float:
        return p["dist"] / p["dist_t"] if p["dist_t"] > 0 else 0.0


# ── Main processing function ──────────────────────────────────
def process_video_job(
    job_id: str,
    video_path: str,
    job_dir: str,
    config: dict,
    jobs: JobStore,
):
    """
    Pipeline: read -> detect + pose -> track -> near/facing test -> attention
    -> classify -> render -> save.
    Called in a thread pool executor from the async FastAPI handler.
    """
    try:
        from ultralytics import YOLO
        import torch

        # ── Config ──────────────────────────────────────────
        confidence   = float(config.get("confidence", 0.40))
        glance_sec   = float(config.get("glance_sec", 2))
        engage_sec   = float(config.get("engage_sec", 5))
        strong_sec   = float(config.get("strong_sec", 10))
        min_look_sec = float(config.get("min_look_sec", 1))     # shorter looks are not counted as viewers
        grace_sec    = float(config.get("grace_sec", 0.7))
        near_ratio   = float(config.get("near_ratio", 0.30))    # box height / frame height
        max_offset   = float(config.get("max_offset", 0.45))    # nose offset in eye-distances
        require_face = bool(config.get("require_face", True))   # also confirm with a frontal-face detector
        kp_conf      = float(config.get("kp_conf", 0.60))
        if not glance_sec <= engage_sec <= strong_sec:
            raise ValueError("Thresholds must satisfy glance <= engage <= strong")
        device = "0" if torch.cuda.is_available() else "cpu"

        # ── Load model ───────────────────────────────────────
        jobs.update(job_id, {"status": "processing", "phase": "loading model"})
        model = YOLO("yolov8n-pose.pt")
        _ = model(np.zeros((640, 640, 3), dtype=np.uint8), verbose=False, device=device)

        # ── Open video ───────────────────────────────────────
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {video_path}")

        W     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        H     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        FPS   = float(cap.get(cv2.CAP_PROP_FPS)) or 25.0
        TOTAL = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        tracker = AttentionTracker(FPS, grace_sec)

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
                    frame, persist=True,
                    conf=confidence, iou=0.45,
                    tracker="bytetrack.yaml",
                    verbose=False, device=device,
                )
            except Exception:
                fid += 1
                continue

            people = []  # (tid, x1, y1, x2, y2, near, facing)
            r = results[0]
            if r.boxes is not None and r.boxes.id is not None and r.keypoints is not None:
                boxes = r.boxes.xyxy.cpu().numpy().astype(int)
                ids   = r.boxes.id.cpu().numpy().astype(int)
                kps   = r.keypoints.xy.cpu().numpy()
                kcs   = r.keypoints.conf.cpu().numpy() if r.keypoints.conf is not None \
                    else np.ones(kps.shape[:2])
                for box, tid, kp, kc in zip(boxes, ids, kps, kcs):
                    x1, y1, x2, y2 = box
                    x1, y1 = max(0, x1), max(0, y1)
                    x2, y2 = min(W - 1, x2), min(H - 1, y2)
                    h = y2 - y1
                    near = h >= near_ratio * H
                    facing = near and is_facing(kp, kc, kp_conf, max_offset)
                    if facing and require_face:
                        facing = has_frontal_face(frame, kp)
                    tracker.update(int(tid), fid, near, facing, (x1 + x2) / 2.0, (y1 + y2) / 2.0, h)
                    people.append((int(tid), x1, y1, x2, y2, near, facing))

            viewers = [t for t, p in tracker.people.items() if p["attention"] >= min_look_sec]
            counts = {GLANCED: 0, LOOKED: 0, ENGAGED: 0, STRONG: 0}
            for t in viewers:
                counts[classify(tracker.attention(t), glance_sec, engage_sec, strong_sec)] += 1
            looking_now = sum(1 for _, _, _, _, _, _, f in people if f)

            fps_buf.append(1.0 / max(time.time() - t0, 1e-6))
            fps = float(np.mean(fps_buf))
            t_video = fid / FPS

            # ── Render ──────────────────────────────────────
            for tid, x1, y1, x2, y2, near, facing in people:
                if not near:  # far away: ignored, drawn faintly
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (110, 110, 110), 1)
                    continue
                a = tracker.attention(tid)
                color = COLORS[classify(a, glance_sec, engage_sec, strong_sec)] if facing else (90, 90, 230)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3 if facing else 2)
                label = f"#{tid} looking {a:.1f}s" if facing else f"#{tid} not looking"
                cv2.putText(frame, label, (x1, max(14, y1 - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

            hud = (f"t={t_video:5.1f}s  looking now: {looking_now}  viewers: {len(viewers)}  "
                   f"engaged: {counts[ENGAGED]}  strong: {counts[STRONG]}")
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
                        "looking_now": looking_now,
                        "viewers":     len(viewers),
                        "engaged":     counts[ENGAGED],
                        "strong":      counts[STRONG],
                        "fps":         round(fps, 1),
                    },
                })

            fid += 1

        cap.release()
        writer.release()

        # ── Final results ────────────────────────────────────
        viewers = []
        for tid, p in sorted(tracker.people.items(), key=lambda kv: kv[1]["first"]):
            if p["attention"] < min_look_sec:
                continue
            viewers.append({
                "person_id":        tid,
                "first_sec":        round(p["first"], 2),
                "last_sec":         round(p["last"], 2),
                "present_sec":      round(p["present"], 2),
                "attention_sec":    round(p["attention"], 2),
                "longest_look_sec": round(p["longest"], 2),
                "looks":            p["looks"],
                "speed":            round(AttentionTracker.speed(p), 2),
                "behaviour":        classify(p["attention"], glance_sec, engage_sec, strong_sec),
            })

        with open(Path(job_dir) / "viewers.csv", "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=list(viewers[0].keys()) if viewers else ["person_id"])
            wr.writeheader()
            wr.writerows(viewers)

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
                "glance_sec":   glance_sec,
                "engage_sec":   engage_sec,
                "strong_sec":   strong_sec,
                "min_look_sec": min_look_sec,
                "ignored":      len(tracker.people) - len(viewers),
            },
            "viewers": viewers,
        })

    except Exception as e:
        jobs.update(job_id, {
            "status": "error",
            "error":  f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()[-800:]}",
        })
