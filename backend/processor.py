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


# ── Distraction: phone, eating / drinking, head down ──────────
L_EAR, R_EAR, L_WRIST, R_WRIST = 3, 4, 9, 10
PHONE_CLS = 67
# COCO: bottle, wine glass, cup, banana, apple, sandwich, orange, hot dog, pizza, donut, cake
FOOD_DRINK_CLS = (39, 40, 41, 46, 47, 48, 49, 52, 53, 54, 55)
OBJ_CLASSES = [PHONE_CLS, *FOOD_DRINK_CLS]


def head_down(kp: np.ndarray, kc: np.ndarray) -> bool:
    """
    Looking down (e.g. at a phone): the ears rise above the eye line. For a head
    held level the ears sit slightly below the eyes. Needs both ears visible.
    """
    if kc[L_EAR] < 0.3 or kc[R_EAR] < 0.3:
        return False
    eye_dist = abs(kp[R_EYE][0] - kp[L_EYE][0])
    if eye_dist < 6:
        return False
    ear_y = (kp[L_EAR][1] + kp[R_EAR][1]) / 2.0
    eye_y = (kp[L_EYE][1] + kp[R_EYE][1]) / 2.0
    return (ear_y - eye_y) / eye_dist < 0.05


def hand_at_mouth(kp: np.ndarray, kc: np.ndarray, reach: float = 1.1) -> bool:
    """A wrist right next to the face: eating, drinking, or a phone at the ear."""
    head = abs(kp[R_EYE][0] - kp[L_EYE][0]) * 2.2
    if head < 12:
        return False
    for w in (L_WRIST, R_WRIST):
        if kc[w] >= 0.5 and np.hypot(*(kp[w] - kp[NOSE])) < reach * head:
            return True
    return False


def busy_with_object(objs, cands):
    """
    Match detected phones / food / drinks to the people holding them.
    objs:  [(cls, (x1, y1, x2, y2))]
    cands: [(tid, (x1, y1, x2, y2), kp, kc)]  near people with a readable face
    Returns {tid: reason}. A phone counts if it is inside the person's box and
    closest to that person's hand; food or a drink counts only near the mouth.
    """
    out = {}
    for cls, (ox1, oy1, ox2, oy2) in objs:
        cx, cy = (ox1 + ox2) / 2.0, (oy1 + oy2) / 2.0
        best, best_d = None, 1e9
        for tid, (x1, y1, x2, y2), kp, kc in cands:
            if not (x1 <= cx <= x2 and y1 <= cy <= y2):
                continue
            pts = [kp[w] for w in (L_WRIST, R_WRIST) if kc[w] >= 0.3] or [kp[NOSE]]
            d = min(np.hypot(cx - pt[0], cy - pt[1]) for pt in pts)
            head = abs(kp[R_EYE][0] - kp[L_EYE][0]) * 2.2
            if cls == PHONE_CLS:
                # in a hand, or held to the ear / face
                ok = min(d, np.hypot(cx - kp[NOSE][0], cy - kp[NOSE][1])) < 3.0 * max(head, 1.0)
            else:
                ok = np.hypot(cx - kp[NOSE][0], cy - kp[NOSE][1]) < 1.8 * max(head, 1.0)
            if ok and d < best_d:
                best, best_d = tid, d
        if best is not None:
            out[best] = "phone" if cls == PHONE_CLS else "eating/drinking"
    return out


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
        ignore_busy  = bool(config.get("ignore_busy", True))    # skip people on a phone / eating / head down
        obj_conf     = float(config.get("obj_conf", 0.25))
        obj_every    = int(config.get("obj_every", 3))          # run the object detector every N frames
        busy_hold    = float(config.get("busy_hold_sec", 1.0))  # keep "busy" this long after an object is seen
        if not glance_sec <= engage_sec <= strong_sec:
            raise ValueError("Thresholds must satisfy glance <= engage <= strong")
        device = "0" if torch.cuda.is_available() else "cpu"

        # ── Load model ───────────────────────────────────────
        jobs.update(job_id, {"status": "processing", "phase": "loading model"})
        model = YOLO("yolov8n-pose.pt")
        _ = model(np.zeros((640, 640, 3), dtype=np.uint8), verbose=False, device=device)
        obj_model = YOLO("yolov8m.pt") if ignore_busy else None
        busy: Dict[int, tuple] = {}   # track id -> (last fid it counts as busy, reason)

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

            people = []  # (tid, x1, y1, x2, y2, near, facing, reason)
            recs = []    # near people: (tid, box, kp, kc, facing, reason, h)
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
                    facing, reason = False, "not looking"
                    if near and is_facing(kp, kc, kp_conf, max_offset):
                        if ignore_busy and head_down(kp, kc):
                            reason = "head down"
                        elif ignore_busy and hand_at_mouth(kp, kc):
                            reason = "hand at face"
                        else:
                            facing = (not require_face) or has_frontal_face(frame, kp)
                    recs.append((int(tid), (x1, y1, x2, y2), kp, kc, near, facing, reason, h))

                # Phones / food / drinks: only worth running when someone looks attentive
                if obj_model is not None and fid % obj_every == 0:
                    cands = [(t, b, kp, kc) for t, b, kp, kc, near, f, _, _ in recs if near and f]
                    if cands:
                        try:
                            od = obj_model(frame, verbose=False, conf=obj_conf, imgsz=1280,
                                           classes=OBJ_CLASSES, device=device)[0]
                            objs = [(int(b.cls), tuple(b.xyxy[0].cpu().numpy())) for b in od.boxes]
                            for t, why in busy_with_object(objs, cands).items():
                                busy[t] = (fid + int(busy_hold * FPS), why)
                        except Exception:
                            pass

                for tid, (x1, y1, x2, y2), kp, kc, near, facing, reason, h in recs:
                    if facing and tid in busy and fid <= busy[tid][0]:
                        facing, reason = False, busy[tid][1]
                    tracker.update(tid, fid, near, facing, (x1 + x2) / 2.0, (y1 + y2) / 2.0, h)
                    people.append((tid, x1, y1, x2, y2, near, facing, reason))

            viewers = [t for t, p in tracker.people.items() if p["attention"] >= min_look_sec]
            counts = {GLANCED: 0, LOOKED: 0, ENGAGED: 0, STRONG: 0}
            for t in viewers:
                counts[classify(tracker.attention(t), glance_sec, engage_sec, strong_sec)] += 1
            looking_now = sum(1 for _, _, _, _, _, _, f, _ in people if f)

            fps_buf.append(1.0 / max(time.time() - t0, 1e-6))
            fps = float(np.mean(fps_buf))
            t_video = fid / FPS

            # ── Render ──────────────────────────────────────
            for tid, x1, y1, x2, y2, near, facing, reason in people:
                if not near:  # far away: ignored, drawn faintly
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (110, 110, 110), 1)
                    continue
                a = tracker.attention(tid)
                color = COLORS[classify(a, glance_sec, engage_sec, strong_sec)] if facing else (90, 90, 230)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3 if facing else 2)
                label = f"#{tid} looking {a:.1f}s" if facing else f"#{tid} {reason}"
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
