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

A second mode, mall places (process_places_job at the end of this file), is for a fixed
camera that sees several shops: the shops are marked by the user and each person's feet
are tested against them (see places.py) to count who entered, left or stopped at each one.
"""

import base64
import csv
import json
import math
import os
import threading
import time
import traceback
from bisect import bisect_right
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import cv2
import numpy as np

import identity as identity_mod
import journeys as journeys_mod
import places as places_mod
import reid as reid_mod
from storage import get_storage


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

    def all(self) -> Dict[str, dict]:
        with self._lock:
            return {k: v.copy() for k, v in self._data.items()}

    def delete(self, job_id: str):
        with self._lock:
            self._data.pop(job_id, None)


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
    return nose_offset(kp) <= max_offset


def nose_offset(kp: np.ndarray) -> float:
    """Nose distance from the eye midpoint in eye-distances: 0 = straight on, larger = head turned."""
    eye_dist = max(abs(kp[R_EYE][0] - kp[L_EYE][0]), 1e-6)
    return abs(kp[NOSE][0] - (kp[L_EYE][0] + kp[R_EYE][0]) / 2.0) / eye_dist


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
    try:
        faces = _FACE_CASCADE.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(24, 24))
    except cv2.error:
        return False  # not confirmed; never let one odd crop fail the whole job
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


def snapshot_score(frame: np.ndarray, box) -> float:
    """Bigger and sharper is better: person height times a sharpness factor."""
    x1, y1, x2, y2 = box
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return 0.0
    small = cv2.resize(crop, (96, max(1, int(96 * crop.shape[0] / max(crop.shape[1], 1)))))
    sharp = cv2.Laplacian(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
    return (y2 - y1) * (50.0 + min(float(sharp), 500.0))


def count_visits(people: list, gap_sec: float) -> int:
    """Separate appearances: tracks closer together than gap_sec are one visit."""
    spans = sorted((p["first"], p["last"]) for p in people)
    visits, end = 0, None
    for first, last in spans:
        if end is None or first - end > gap_sec:
            visits += 1
        end = last if end is None else max(end, last)
    return visits


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


# ── Video output ──────────────────────────────────────────────
def open_writer(path: str, fps: float, size: tuple) -> "cv2.VideoWriter":
    """Prefer browser-playable H.264, fall back to mp4v."""
    for codec in ("avc1", "mp4v"):
        w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*codec), fps, size)
        if w.isOpened():
            return w
        w.release()
    raise RuntimeError("Could not open a video writer")


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
        capture      = bool(config.get("capture_images", True)) # save a snapshot of each engaged viewer
        use_reid     = bool(config.get("reid", True))           # treat a returning person as the same person
        reid_thresh  = float(config.get("reid_threshold", 0.88))
        reid_margin  = float(config.get("reid_margin", 0.02))
        reid_every   = int(config.get("reid_every", 3))         # take an appearance sample every N frames
        visit_gap    = float(config.get("visit_gap_sec", 5))    # away longer than this = a new visit
        if not glance_sec <= engage_sec <= strong_sec:
            raise ValueError("Thresholds must satisfy glance <= engage <= strong")
        device = "0" if torch.cuda.is_available() else "cpu"

        # ── Load model ───────────────────────────────────────
        jobs.update(job_id, {"status": "processing", "phase": "loading model"})
        model = YOLO("yolov8n-pose.pt")
        _ = model(np.zeros((640, 640, 3), dtype=np.uint8), verbose=False, device=device)
        obj_model = YOLO("yolov8m.pt") if ignore_busy else None
        busy: Dict[int, tuple] = {}   # track id -> (last fid it counts as busy, reason)
        snaps: Dict[int, dict] = {}   # track id -> best snapshot so far
        storage = get_storage(job_dir)

        # ── Open video ───────────────────────────────────────
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {video_path}")

        W     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        H     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        FPS   = float(cap.get(cv2.CAP_PROP_FPS)) or 25.0
        TOTAL = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        tracker = AttentionTracker(FPS, grace_sec)
        gallery = reid_mod.Gallery(reid_thresh, reid_margin,
                                   stitch_threshold=float(config.get("stitch_threshold", 0.76)),
                                   stitch_gap=int(float(config.get("stitch_gap_sec", 1.5)) * FPS))

        def group_totals() -> Dict[int, float]:
            """Attention per person, summing every tracker ID matched to the same person."""
            tot: Dict[int, float] = {}
            for t, pr in tracker.people.items():
                k = gallery.pid(t)
                tot[k] = tot.get(k, 0.0) + pr["attention"]
            return tot

        jobs.update(job_id, {
            "total_frames": TOTAL,
            "resolution": f"{W}x{H}",
            "source_fps": FPS,
        })

        # ── Video writer ─────────────────────────────────────
        out_path = str(Path(job_dir) / "annotated.mp4")
        writer = open_writer(out_path, FPS, (W, H))

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

                # Same-person matching (frame is still clean here)
                if use_reid:
                    active = {rc[0] for rc in recs}
                    for rc in recs:
                        t = rc[0]
                        gallery.seen(t, fid, rc[1])
                        if rc[4] and (fid + t) % reid_every == 0 and gallery.tracks[t]["samples"] < 30:
                            sig = reid_mod.embed(frame, rc[1])
                            if sig:
                                gallery.add(t, fid, sig)
                        gallery.try_assign(t, active)

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
                    if capture and facing:  # taken before any boxes are drawn on the frame
                        # prefer the most frontal frame: weight size/sharpness by how straight the head is
                        sc = snapshot_score(frame, (x1, y1, x2, y2)) * max(0.2, 1.0 - nose_offset(kp) / max_offset)
                        best = snaps.get(tid)
                        if best is None or sc > best["score"]:
                            pad_x, pad_y = int((x2 - x1) * 0.05), int(h * 0.03)
                            bx1, by1 = max(0, x1 - pad_x), max(0, y1 - pad_y)
                            bx2, by2 = min(W, x2 + pad_x), min(H, y2 + pad_y)
                            snaps[tid] = {
                                "score": sc, "img": frame[by1:by2, bx1:bx2].copy(),
                                "sec": round(fid / FPS, 2), "bbox": [int(x1), int(y1), int(x2), int(y2)],
                            }

            totals = group_totals()
            viewers = [k for k, a in totals.items() if a >= min_look_sec]
            counts = {GLANCED: 0, LOOKED: 0, ENGAGED: 0, STRONG: 0}
            for k in viewers:
                counts[classify(totals[k], glance_sec, engage_sec, strong_sec)] += 1
            looking_now = sum(1 for _, _, _, _, _, _, f, _ in people if f)

            fps_buf.append(1.0 / max(time.time() - t0, 1e-6))
            fps = float(np.mean(fps_buf))
            t_video = fid / FPS

            # ── Render ──────────────────────────────────────
            for tid, x1, y1, x2, y2, near, facing, reason in people:
                if not near:  # far away: ignored, drawn faintly
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (110, 110, 110), 1)
                    continue
                pid = gallery.pid(tid)
                a = totals.get(pid, 0.0)
                color = COLORS[classify(a, glance_sec, engage_sec, strong_sec)] if facing else (90, 90, 230)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3 if facing else 2)
                label = f"#{pid} looking {a:.1f}s" if facing else f"#{pid} {reason}"
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
        groups: Dict[int, list] = {}
        for tid in tracker.people:
            groups.setdefault(gallery.pid(tid), []).append(tid)

        viewers = []
        for pid, tids in sorted(groups.items(), key=lambda kv: min(tracker.people[t]["first"] for t in kv[1])):
            ps = [tracker.people[t] for t in tids]
            attention = sum(q["attention"] for q in ps)
            if attention < min_look_sec:
                continue
            dist_t = sum(q["dist_t"] for q in ps)
            viewers.append({
                "person_id":        pid,
                "first_sec":        round(min(q["first"] for q in ps), 2),
                "last_sec":         round(max(q["last"] for q in ps), 2),
                "present_sec":      round(sum(q["present"] for q in ps), 2),
                "attention_sec":    round(attention, 2),
                "longest_look_sec": round(max(q["longest"] for q in ps), 2),
                "looks":            sum(q["looks"] for q in ps),
                "visits":           count_visits(ps, visit_gap),
                "speed":            round(sum(q["dist"] for q in ps) / dist_t, 2) if dist_t > 0 else 0.0,
                "behaviour":        classify(attention, glance_sec, engage_sec, strong_sec),
                "track_ids":        sorted(tids),
                "image":            "",
            })

        # Snapshot + JSON for engaged and strongly engaged viewers only
        captured = []
        if capture:
            for v in viewers:
                # best snapshot over every tracker ID that belongs to this person
                snap = max((snaps[t] for t in v["track_ids"] if t in snaps),
                           key=lambda sn: sn["score"], default=None)
                if v["behaviour"] not in (ENGAGED, STRONG) or snap is None:
                    continue
                ok, jpg = cv2.imencode(".jpg", snap["img"], [cv2.IMWRITE_JPEG_QUALITY, 90])
                if not ok:
                    continue
                v["image"] = storage.save(f"captures/person_{v['person_id']}.jpg", jpg.tobytes())
                captured.append({**v, "snapshot_sec": snap["sec"], "bbox": snap["bbox"]})
            doc = {
                "job_id":       job_id,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source":       {"duration_sec": round(fid / max(FPS, 1), 1), "resolution": f"{W}x{H}",
                                 "fps": round(FPS, 1)},
                "thresholds":   {"glance_sec": glance_sec, "engage_sec": engage_sec,
                                 "strong_sec": strong_sec, "min_look_sec": min_look_sec},
                "engaged_viewers": captured,
            }
            storage.save("captures/engaged.json", json.dumps(doc, indent=2).encode("utf-8"))

        with open(Path(job_dir) / "viewers.csv", "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=list(viewers[0].keys()) if viewers else ["person_id"])
            wr.writeheader()
            wr.writerows({**v, "track_ids": ";".join(map(str, v["track_ids"]))} for v in viewers)

        # Audit trail of every same-person decision
        (Path(job_dir) / "reid.json").write_text(json.dumps({
            "enabled": use_reid, "threshold": reid_thresh, "margin": reid_margin,
            "tracks": len(tracker.people), "people": len(groups),
            "decisions": gallery.log,
        }, indent=2), encoding="utf-8")

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
                "ignored":      len(groups) - len(viewers),
                "tracks":       len(tracker.people),
                "people":       len(groups),
                "reid":         use_reid,
                "captured":     len(captured),
            },
            "viewers": viewers,
        })

    except Exception as e:
        jobs.update(job_id, {
            "status": "error",
            "error":  f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()[-800:]}",
        })


# ── Mall places mode ──────────────────────────────────────────
# A model file is a pickle, so only names from this list are ever loaded, never one the client sent
MALL_MODELS = ("yolov8n.pt", "yolov8s.pt", "yolov8m.pt", "yolov8l.pt")
MALL_TRACKER = str(Path(__file__).with_name("trackers") / "bytetrack_mall.yaml")
STAY_SEC = (2.5, 0.5, 30.0)    # default, lowest, highest: inside this long counts as entered
STOP_SEC = (3.0, 0.5, 120.0)   # the same for standing still in front this long counting as stopped
MALL_VIDEO_WIDTH = 1280   # the annotated video is scaled down to this width
BADGE_SEC = 2.0           # how long an event badge stays on the annotated video

EVENT_COLORS = {"enter": (0, 200, 0), "exit": (0, 140, 255), "peek": (170, 170, 170), "stop": (0, 215, 255)}
EVENT_FIELDS = ["person_id", "track_id", "event", "place", "time_s", "frame", "duration_s",
                "confidence", "feet_estimated", "reason"]


def read_setting(config: dict, key: str, default: float, lo: float, hi: float) -> float:
    """A number from the client's config, held inside [lo, hi] so a bad value cannot stall or crash the job."""
    v = float(config.get(key, default))
    if not math.isfinite(v):
        raise ValueError(f"{key} must be a number")
    return min(max(v, lo), hi)


def csv_safe(text: str) -> str:
    """A shop name is typed by the user: one that starts like a spreadsheet formula is made plain text."""
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def draw_pill(frame: np.ndarray, text: str, x: float, y: float, bg: tuple, scale: float = 0.4, alpha: float = 0.75):
    """A small label on a tinted box, moved if needed so it stays inside the frame."""
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
    w, h = tw + 8, th + base + 6
    x, y = int(min(max(x, 0), frame.shape[1] - w)), int(min(max(y, 0), frame.shape[0] - h))
    roi = frame[y:y + h, x:x + w]
    cv2.addWeighted(np.full_like(roi, bg), alpha, roi, 1.0 - alpha, 0, roi)
    cv2.putText(frame, text, (x + 4, y + h - base - 2), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 1, cv2.LINE_AA)


def preview_jpeg(frame: np.ndarray, boxes: list, width: int = 640) -> str:
    """
    The live preview: the frame scaled to `width` with the tracked people on it, as base64 JPEG. The shops are not
    drawn here: the page draws them over the picture, the same way it does over the finished video.
    """
    sc = width / frame.shape[1]
    small = cv2.resize(frame, (width, max(1, int(frame.shape[0] * sc))))
    draw_people(small, boxes, sc, lambda t: f"#{t}")
    _, jpg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return base64.b64encode(jpg.tobytes()).decode()


def draw_people(frame: np.ndarray, boxes: list, sc: float, name):
    """Tracked people: a thin light box and a small ID label. name(track id) is the label's text."""
    for tid, x1, y1, x2, y2 in boxes:
        p1, p2 = (int(x1 * sc), int(y1 * sc)), (int(x2 * sc), int(y2 * sc))
        cv2.rectangle(frame, p1, p2, (225, 225, 225), 1, cv2.LINE_AA)
        draw_pill(frame, name(tid), p1[0], p1[1] - 16, (40, 40, 40), 0.35, 0.65)


def render_places_video(video_path: str, out_path: str, shops: list, seen: Dict[int, list], feet: Dict[int, list],
                        events: list, name, name_of, fps: float, stride: int, on_progress=None):
    """
    Second pass over the video for the annotated output: tracked people, their feet (yellow when estimated from
    the head) and a badge at the door for every event. The shops are not drawn here: the page draws them over the
    video, where they can be switched off. It plays at normal speed on the analysed frames.
    seen: {fid: [(track_id, x1, y1, x2, y2)]}    feet: {track_id: [(fid, x, feet_row, estimated, body_h)]}
    name(track id) and name_of(person id) are the texts of a person's label and of an event badge.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video_path}")
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    sc = min(1.0, MALL_VIDEO_WIDTH / W)
    size = (int(W * sc) // 2 * 2, int(H * sc) // 2 * 2)   # H.264 needs even sizes
    writer = open_writer(out_path, fps / stride, size)

    feet_at = defaultdict(list)
    for pts in feet.values():
        for fid, x, y, estimated, _ in pts:
            feet_at[fid].append((x, y, estimated))
    # event badges go on the outside of the door
    badge_at = {}
    for s in shops:
        mid = ((s["a"][0] + s["b"][0]) / 2 * sc, (s["a"][1] + s["b"][1]) / 2 * sc)
        badge_at[s["name"]] = (mid[0] - s["inward"][0] * 0.05 * max(size), mid[1] - s["inward"][1] * 0.05 * max(size))
    counted = {k: sorted(e["frame"] for e in events if e["event"] == k) for k in ("enter", "exit")}
    badge_frames = int(BADGE_SEC * fps)

    fid = 0
    while cap.grab():
        if fid % stride == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            if frame.shape[1] != size[0] or frame.shape[0] != size[1]:
                frame = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
            draw_people(frame, seen.get(fid, []), sc, name)
            for x, y, estimated in feet_at.get(fid, []):
                cv2.circle(frame, (int(x * sc), int(y * sc)), 4, (30, 30, 30), -1, cv2.LINE_AA)
                cv2.circle(frame, (int(x * sc), int(y * sc)), 3, (0, 230, 255) if estimated else (255, 255, 255), -1, cv2.LINE_AA)

            stacked = defaultdict(int)
            for e in events:
                if 0 <= fid - e["frame"] < badge_frames:
                    x, y = badge_at[e["place"]]
                    n = stacked[e["place"]]
                    stacked[e["place"]] += 1
                    draw_pill(frame, f"{name_of(e['person_id'])} {e['event'].upper()}", x - 30, y + 20 * n, EVENT_COLORS[e["event"]], 0.42, 0.85)

            draw_pill(frame, f"t {fid / fps:.1f}s   in view {len(seen.get(fid, []))}   "
                             f"entered {bisect_right(counted['enter'], fid)}   exited {bisect_right(counted['exit'], fid)}",
                      8, 8, (30, 30, 30), 0.45, 0.6)
            writer.write(frame)
            if on_progress and total and fid % (stride * 10) == 0:
                on_progress(fid / total)
        fid += 1
    cap.release()
    writer.release()


def replace_file(src: Path, dst: Path, tries: int = 10, wait: float = 0.5):
    """os.replace that waits a little while the destination is open elsewhere (Windows refuses until it is closed)."""
    for attempt in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == tries - 1:
                raise PermissionError(f"{dst.name} is open in another program (is the video playing?). Close it and try again.")
            time.sleep(wait)


def save_tracks(job_dir: str, data: dict):
    """Keep the tracked people (tracks.json) so the marks can be adjusted later without detecting everyone again."""
    (Path(job_dir) / "tracks.json").write_text(json.dumps({
        **data,
        "tracks": {str(t): [[o[0], *(round(v, 1) for v in o[1:])] for o in obs] for t, obs in data["tracks"].items()},
        "person_of": {str(t): p for t, p in data.get("person_of", {}).items()},
        "signatures": {str(t): rows for t, rows in data.get("signatures", {}).items()},
    }), encoding="utf-8")


def load_tracks(job_dir: str) -> dict:
    """The tracked people saved by a mall places job (tracks.json), with track ids and boxes as the analysis wants them."""
    raw = json.loads((Path(job_dir) / "tracks.json").read_text(encoding="utf-8"))
    raw["tracks"] = {int(t): [tuple(o) for o in obs] for t, obs in raw["tracks"].items()}
    raw["person_of"] = {int(t): p for t, p in raw.get("person_of", {}).items()}   # jobs from before visitor ids carry these
    raw["signatures"] = {int(t): rows for t, rows in raw.get("signatures", {}).items()}
    return raw


def analyze_places_job(job_id: str, video_path: str, job_dir: str, shops: list, data: dict, stay_sec: float,
                       stop_sec: float, memory_sec: float, settings: dict, stats: dict, jobs: JobStore):
    """
    Everything after the people are tracked: who is who, shop events and metrics, the result files and the
    annotated video. It runs when tracking finishes and again, on the saved tracks, when the user adjusts the marks.
    data: width, height, fps, stride, last_fid, tracks, signatures (see load_tracks; person_of only on jobs from
    before visitor ids). memory_sec: how long a lost person is waited for. settings: what the result files record
    about the run. stats: the job's stats, to which the new numbers are added.
    """
    W, H, FPS, stride = data["width"], data["height"], data["fps"], data["stride"]
    jobs.update(job_id, {"phase": "matching people", "progress": 90, "preview_frame": None})
    who = None
    if settings.get("reid", True) and data["signatures"]:
        who = identity_mod.resolve(data, places_mod.to_pixels(shops, W, H), memory_sec)
        tracks, person_of, origin = who["pieces"], who["person_of"], who["origin"]
    else:
        tracks, person_of, origin = data["tracks"], data["person_of"], {}
    jobs.update(job_id, {"phase": "finding shop events"})
    res = places_mod.analyze(tracks, person_of, shops, W, H, FPS, data["last_fid"], stay_sec, stop_sec)
    for e in res["events"]:
        if e["track_id"] is not None:
            e["track_id"] = origin.get(e["track_id"], e["track_id"])   # the tracker's id, not the id of a cut piece
    metrics = journeys_mod.summarize(res["events"], res["front"], shops)
    visitors = who["visitors"] if who else []
    people = len({person_of.get(t, t) for t in res["feet"]})

    # The files are written under temporary names and only replace the real ones once all of them worked, so a
    # failure (or a download while this runs) never sees half of a new result
    out_dir = Path(job_dir)
    tmp = {name: out_dir / f"tmp_{name}" for name in ("place_events.csv", "place_metrics.json", "identity.json", "annotated.mp4")}
    try:
        # utf-8 with a BOM so Excel reads shop names in any script; a name that starts like a formula is made plain text
        with open(tmp["place_events.csv"], "w", newline="", encoding="utf-8-sig") as f:
            wr = csv.DictWriter(f, fieldnames=EVENT_FIELDS)
            wr.writeheader()
            wr.writerows({**e, "place": csv_safe(e["place"])} for e in res["events"])
        tmp["place_metrics.json"].write_text(json.dumps({
            "places": shops, "metrics": metrics, "front": res["front"], "height_model": res["height_model"],
            "settings": {**settings, "stay_sec": stay_sec, "stop_sec": stop_sec, "memory_sec": memory_sec},
        }, indent=2), encoding="utf-8")
        # Audit trail of every cut and every join: what each was based on
        tmp["identity.json"].write_text(json.dumps({
            "enabled": who is not None, "memory_sec": memory_sec, "tracks": len(data["tracks"]),
            "pieces": len(tracks), "visitors": len(visitors), "cuts": who["cuts"] if who else [],
            "links": who["links"] if who else [],
        }, indent=2), encoding="utf-8")

        jobs.update(job_id, {"phase": "rendering video"})
        seen: Dict[int, list] = {}   # only people: a mannequin the detector found is not drawn
        for tid in res["feet"]:
            for fid, x1, y1, x2, y2 in tracks[tid]:
                seen.setdefault(fid, []).append((tid, x1, y1, x2, y2))
        name_of = identity_mod.label if who else (lambda p: f"#{p}")
        render_places_video(
            video_path, str(tmp["annotated.mp4"]), places_mod.to_pixels(shops, W, H), seen, res["feet"],
            res["events"], (lambda t: name_of(person_of.get(t, t))), name_of, FPS, stride,
            on_progress=lambda frac: jobs.update(job_id, {"progress": 90 + int(min(frac, 1.0) * 9)}),
        )
        # The video goes first: a browser playing or downloading it keeps it open, and Windows will not replace an
        # open file. If that happens nothing has changed yet and the old result stands whole.
        for name in ("annotated.mp4", "place_events.csv", "place_metrics.json", "identity.json"):
            replace_file(tmp[name], out_dir / name)
    except Exception:
        for path in tmp.values():
            path.unlink(missing_ok=True)
        raise
    (out_dir / "results.zip").unlink(missing_ok=True)   # a bundle built from the old result must not be served

    jobs.update(job_id, {
        "status":   "done",
        "phase":    "",
        "progress": 100,
        "stats": {
            **stats,
            "people":         people,
            "entered":        metrics["overlap_entered"]["people"],
            "stay_sec":       stay_sec,
            "stop_sec":       stop_sec,
            "memory_sec":     memory_sec,
            "estimated_feet": res["estimated_share"],
        },
        "places_result": {
            "places":       shops,
            "events":       res["events"],
            "metrics":      metrics,
            "front":        res["front"],
            "height_model": res["height_model"],
            "visitors":     visitors,
        },
    })


def process_places_job(
    job_id: str,
    video_path: str,
    job_dir: str,
    config: dict,
    jobs: JobStore,
):
    """
    Mall places mode: read -> detect + track -> match returning people -> shop events from the feet
    -> metrics -> annotated video. The shops are marked by the user and checked in places.parse_places.
    Called in a thread pool executor from the async FastAPI handler, like process_video_job.
    """
    try:
        from ultralytics import YOLO
        import torch

        # ── Config ──────────────────────────────────────────
        shops = places_mod.parse_places(config.get("places"))
        model_name   = str(config.get("model", "yolov8m.pt"))
        if model_name not in MALL_MODELS:
            raise ValueError(f"Unknown model: {model_name}")
        confidence   = read_setting(config, "confidence", 0.35, 0.05, 0.95)  # people are small: a lower bar than the stand mode
        iou          = read_setting(config, "iou", 0.6, 0.3, 0.9)            # crowds: do not suppress people standing close together
        imgsz        = int(read_setting(config, "imgsz", 1280, 320, 1920))
        analysis_fps = read_setting(config, "analysis_fps", 12, 2, 30)       # frames analysed per second of video
        stay_sec     = read_setting(config, "stay_sec", *STAY_SEC)           # inside this long counts as entered
        stop_sec     = read_setting(config, "stop_sec", *STOP_SEC)           # standing still in front this long counts as stopped
        memory_sec   = read_setting(config, "memory_sec", *identity_mod.MEMORY_SEC)   # a lost person is waited for this long
        use_reid     = bool(config.get("reid", True))                        # keep one visitor id on a person for the whole video
        reid_every   = int(read_setting(config, "reid_every", 3, 1, 30))     # take a colour sample of a person every N analysed frames
        device = "0" if torch.cuda.is_available() else "cpu"

        # ── Load model ───────────────────────────────────────
        jobs.update(job_id, {"status": "processing", "phase": "loading model"})
        model = YOLO(model_name)
        _ = model(np.zeros((640, 640, 3), dtype=np.uint8), verbose=False, device=device)

        # ── Open video ───────────────────────────────────────
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {video_path}")

        W     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        H     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        FPS   = float(cap.get(cv2.CAP_PROP_FPS)) or 25.0
        TOTAL = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        stride = max(1, round(FPS / analysis_fps))

        shops_px = places_mod.to_pixels(shops, W, H)
        sampler = identity_mod.Sampler(reid_every, stride)
        jobs.update(job_id, {
            "phase": "tracking people",
            "total_frames": TOTAL,
            "resolution": f"{W}x{H}",
            "source_fps": FPS,
        })

        tracks: Dict[int, list] = {}   # track id -> [(fid, x1, y1, x2, y2)]
        fps_buf = deque(maxlen=30)
        preview_every = max(1, (TOTAL // stride) // 100) if TOTAL > 0 else 5
        fid = k = 0

        # ── Frame loop (every `stride`-th frame) ─────────────
        while cap.grab():
            if fid % stride:
                fid += 1
                continue
            ok, frame = cap.retrieve()
            if not ok:
                break
            t0 = time.time()

            try:
                results = model.track(
                    frame, persist=True, classes=[0],
                    conf=confidence, iou=iou, imgsz=imgsz,
                    tracker=MALL_TRACKER,
                    verbose=False, device=device,
                )
            except Exception:
                fid += 1
                continue

            boxes = []
            r = results[0]
            if r.boxes is not None and r.boxes.id is not None:
                for box, tid in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.id.cpu().numpy().astype(int)):
                    x1, y1, x2, y2 = (float(v) for v in box)
                    boxes.append((int(tid), x1, y1, x2, y2))
                    tracks.setdefault(int(tid), []).append((fid, x1, y1, x2, y2))

            # Shirt and trousers colours for telling people apart later (the frame is still clean here)
            if use_reid:
                for tid, x1, y1, x2, y2 in boxes:
                    sampler.offer(tid, fid, frame, (x1, y1, x2, y2), [b[1:] for b in boxes if b[0] != tid])

            fps_buf.append(1.0 / max(time.time() - t0, 1e-6))

            if k % preview_every == 0:
                jobs.update(job_id, {
                    "progress":         min(89, int(fid / TOTAL * 90)) if TOTAL > 0 else 0,   # the frame count can be wrong
                    "processed_frames": fid,
                    "fps":              round(float(np.mean(fps_buf)), 1),
                    "preview_frame":    preview_jpeg(frame, boxes),
                    "frame_data": {
                        "time_sec":   round(fid / FPS, 1),
                        "people_now": len(boxes),
                        "tracks":     len(tracks),
                        "fps":        round(float(np.mean(fps_buf)), 1),
                    },
                })

            fid += 1
            k += 1

        cap.release()

        save_tracks(job_dir, {"width": W, "height": H, "fps": FPS, "stride": stride, "last_fid": fid - 1,
                              "tracks": tracks, "signatures": sampler.samples})
        data = load_tracks(job_dir)   # boxes are saved to a tenth of a pixel: the first analysis uses the saved ones too

        jobs.update(job_id, {"processed_frames": fid})
        analyze_places_job(
            job_id, video_path, job_dir, shops, data, stay_sec, stop_sec, memory_sec,
            {"model": model_name, "imgsz": imgsz, "analysis_fps": round(FPS / stride, 1),
             "confidence": confidence, "reid": use_reid},
            {"duration_sec": round(fid / max(FPS, 1), 1), "resolution": f"{W}x{H}", "source_fps": round(FPS, 1),
             "total_frames": fid, "tracks": len(tracks), "model": model_name,
             "analysis_fps": round(FPS / stride, 1), "reid": use_reid},
            jobs,
        )

    except Exception as e:
        jobs.update(job_id, {
            "status": "error",
            "error":  f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()[-800:]}",
        })
