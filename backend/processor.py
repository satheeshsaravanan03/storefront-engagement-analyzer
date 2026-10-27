"""
processor.py
============
The full YOLOv8 + ByteTrack people counting pipeline,
adapted to run as a background job and report live progress
through the JobStore shared with the FastAPI main process.
"""

import base64
import io
import os
import smtplib
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import time
import threading
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import cv2
import matplotlib
matplotlib.use("Agg")          # non-GUI backend for server
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter

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


# ── Zone & Line classes ────────────────────────────────────────
class VirtualLine:
    def __init__(self, name, position_ratio, orientation="horizontal"):
        self.name        = name
        self.pos         = position_ratio
        self.orientation = orientation
        self.count_in    = 0
        self.count_out   = 0
        self._prev       = {}

    def _side(self, cx, cy, W, H):
        if self.orientation == "horizontal":
            return 1 if cy > self.pos * H else -1
        return 1 if cx > self.pos * W else -1

    def update(self, tid, cx, cy, W, H):
        cur = self._side(cx, cy, W, H)
        event = None
        if tid in self._prev and self._prev[tid] != cur:
            if cur == 1:
                self.count_in  += 1; event = "in"
            else:
                self.count_out += 1; event = "out"
        self._prev[tid] = cur
        return event


class PolygonZone:
    def __init__(self, name, points_ratio, alert_threshold, zone_type="general"):
        self.name            = name
        self.pts_ratio       = np.array(points_ratio, dtype=np.float32)
        self.alert_threshold = alert_threshold
        self.zone_type       = zone_type
        self.current_count   = 0
        self.max_count       = 0
        self.alert_active    = False

    def _pixel_pts(self, W, H):
        p = self.pts_ratio.copy()
        p[:, 0] *= W; p[:, 1] *= H
        return p.astype(np.int32)

    def contains(self, cx, cy, W, H):
        pts = self._pixel_pts(W, H)
        return cv2.pointPolygonTest(pts, (float(cx), float(cy)), False) >= 0

    def count_people(self, centroids, W, H):
        n = sum(1 for _, cx, cy in centroids if self.contains(cx, cy, W, H))
        self.current_count = n
        self.max_count = max(self.max_count, n)
        self.alert_active = n >= self.alert_threshold
        return n

    def draw(self, frame):
        H, W = frame.shape[:2]
        pts = self._pixel_pts(W, H)
        overlay = frame.copy()
        fill = (0, 0, 200) if self.alert_active else (200, 0, 200)
        cv2.fillPoly(overlay, [pts], fill)
        cv2.addWeighted(overlay, 0.18, frame, 0.82, 0, frame)
        cv2.polylines(frame, [pts], True, fill, 2)
        cx, cy = pts.mean(axis=0).astype(int)
        status = "ALERT!" if self.alert_active else self.zone_type.upper()
        cv2.putText(frame, f"{self.name}: {self.current_count} [{status}]",
                    (cx - 80, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (0, 0, 255) if self.alert_active else (255, 255, 255), 2)
        return frame


# ── HUD ───────────────────────────────────────────────────────
def draw_hud(frame, stats):
    H, W = frame.shape[:2]
    pw = 340
    items = [
        ("CROWDVISION v2.0", (0, 210, 255), 0.65),
        (datetime.now().strftime("%H:%M:%S"), (150, 150, 150), 0.50),
        (f"FPS: {stats['fps']:.1f}", (150, 150, 150), 0.50),
        (f"Detected:  {stats['live_count']}", (0, 255, 150), 0.60),
        (f"Total IN:  {stats['count_in']}", (0, 200, 0), 0.60),
        (f"Total OUT: {stats['count_out']}", (0, 80, 255), 0.60),
        (f"Occupancy: {stats['occupancy']}", (0, 0, 255) if stats['occupancy'] >= stats.get('overcrowd_thresh', 10) else (255, 255, 255), 0.60),
        (f"Rate: {stats['entry_rate']:.2f}/s", (200, 200, 0), 0.60),
    ]
    if stats.get("avg_dwell") is not None:
        items.append((f"Avg Wait: {stats['avg_dwell']:.1f}s", (0, 220, 220), 0.60))

    ph = len(items) * 26 + 16
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (pw, ph), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)

    y = 22
    for txt, col, sc in items:
        cv2.putText(frame, txt, (8, y), cv2.FONT_HERSHEY_SIMPLEX, sc, col, 2)
        y += 26
    return frame


# ── Alert Engine ──────────────────────────────────────────────
class AlertEngine:
    def __init__(self, log_path, email_cfg=None):
        self.history      = []
        self.log_path     = log_path
        self._cooldowns   = {}
        self._above_since = {}
        self._email_sent  = set()   # prevent duplicate emails per job
        self.email_cfg    = email_cfg or {}

        with open(log_path, "w") as f:
            f.write("timestamp,zone,alert_type,level,value,threshold\n")

    def _send_email(self, subject, body):
        """Send alert email via Gmail SMTP. Runs in background thread."""
        cfg = self.email_cfg
        if not cfg.get("enabled"):
            return
        def _do_send():
            try:
                msg = MIMEMultipart()
                msg["From"]    = cfg["from"]
                msg["To"]      = cfg["to"]
                msg["Subject"] = subject
                msg.attach(MIMEText(body, "plain"))
                with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as s:
                    s.login(cfg["from"], cfg["password"])
                    s.sendmail(cfg["from"], cfg["to"], msg.as_string())
                print(f"  Email sent to {cfg['to']}: {subject}")
            except Exception as e:
                print(f"  Email failed: {e}")
        threading.Thread(target=_do_send, daemon=True).start()

    def _can_fire(self, key, cooldown=8):
        now = time.time()
        if now - self._cooldowns.get(key, 0) > cooldown:
            self._cooldowns[key] = now
            return True
        return False

    def check(self, zones, entry_rate, sustained_sec):
        """
        Check all zones for threshold breaches.
        sustained_sec=0 means fire email immediately on first breach.
        """
        now = time.time()
        for z in zones:
            # Always compute these so they are available for email block
            atype = "QUEUE_OVERFLOW" if z.zone_type == "queue" else "OVERCROWDING"
            level = "CRITICAL" if z.current_count >= z.alert_threshold * 1.5 else "WARNING"
            key   = f"{z.name}_{atype}"

            if z.current_count >= z.alert_threshold:
                # Record when threshold was FIRST exceeded (for sustained timer)
                if z.name not in self._above_since:
                    self._above_since[z.name] = now

                # Log to CSV + history (with cooldown to avoid spam every frame)
                if self._can_fire(key):
                    ts = datetime.now().isoformat()
                    self.history.append({
                        "timestamp": ts, "zone": z.name,
                        "type": atype, "level": level,
                        "value": z.current_count, "threshold": z.alert_threshold,
                    })
                    with open(self.log_path, "a") as f:
                        f.write(f"{ts},{z.name},{atype},{level},"
                                f"{z.current_count},{z.alert_threshold}\n")

                # Email logic: fire once when sustained >= sustained_sec
                sustained  = now - self._above_since[z.name]
                email_key  = f"{z.name}_email"
                should_send = (sustained >= sustained_sec and
                               email_key not in self._email_sent)

                if should_send:
                    self._email_sent.add(email_key)
                    delay_msg = (
                        "immediately on first breach"
                        if sustained_sec == 0
                        else f"sustained {sustained:.0f}s (threshold: {sustained_sec}s)"
                    )
                    subject = (
                        f"[CrowdVision] {level}: {atype.replace('_',' ')} — {z.name}"
                    )
                    body = (
                        f"CROWDVISION ALERT\n"
                        f"{'='*45}\n"
                        f"Time        : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"Zone        : {z.name}\n"
                        f"Alert Type  : {atype.replace('_', ' ')}\n"
                        f"Level       : {level}\n"
                        f"Count       : {z.current_count} persons\n"
                        f"Threshold   : {z.alert_threshold} persons\n"
                        f"Trigger     : {delay_msg}\n"
                        f"{'='*45}\n"
                        f"Please take immediate action.\n\n"
                        f"-- CrowdVision Alert System"
                    )
                    print(f"  Firing email: {subject} | enabled={self.email_cfg.get('enabled')} | to={self.email_cfg.get('to')}")
                    self._send_email(subject, body)

            else:
                # Count dropped below threshold — reset timers
                self._above_since.pop(z.name, None)
                self._email_sent.discard(f"{z.name}_email")

        # Rapid influx check
        if entry_rate > 2.5 and self._can_fire("Entrance_RAPID_INFLUX"):
            ts = datetime.now().isoformat()
            self.history.append({
                "timestamp": ts, "zone": "Entrance",
                "type": "RAPID_INFLUX", "level": "WARNING",
                "value": round(entry_rate, 1), "threshold": 2.5,
            })
            with open(self.log_path, "a") as f:
                f.write(f"{ts},Entrance,RAPID_INFLUX,WARNING,{entry_rate:.1f},2.5\n")
            if "RAPID_INFLUX_email" not in self._email_sent:
                self._email_sent.add("RAPID_INFLUX_email")
                self._send_email(
                    "[CrowdVision] WARNING: Rapid crowd influx",
                    f"Entry rate {entry_rate:.1f} persons/sec exceeded limit.\n"
                    f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"-- CrowdVision Alert System"
                )

# ── Analytics Tracker ─────────────────────────────────────────
class AnalyticsTracker:
    def __init__(self, output_dir):
        self.output_dir   = output_dir
        self.frame_log    = []
        self.event_log    = []
        self.dwell_log    = []
        self.dwell_times  = defaultdict(list)
        self._zone_entry  = defaultdict(dict)
        self._entry_times = deque()
        self.heatmap_acc  = None
        self.trails       = defaultdict(lambda: deque(maxlen=25))
        self.total_in = self.total_out = self.peak_occupancy = 0
        self._last_flush  = time.time()

    def log_frame(self, fid, fps, zone_counts, total_in, total_out):
        self.total_in  = total_in
        self.total_out = total_out
        occ = max(0, total_in - total_out)
        self.peak_occupancy = max(self.peak_occupancy, occ)
        entry = {"frame": fid, "timestamp": datetime.now().isoformat(),
                 "fps": round(fps, 1), "total_in": total_in,
                 "total_out": total_out, "occupancy": occ}
        entry.update({f"zone_{k}": v for k, v in zone_counts.items()})
        self.frame_log.append(entry)
        if time.time() - self._last_flush > 3:
            self._flush(); self._last_flush = time.time()

    def log_event(self, tid, etype, zone, cx, cy):
        self.event_log.append({"timestamp": datetime.now().isoformat(),
                                "track_id": tid, "event": etype,
                                "zone": zone, "cx": cx, "cy": cy})
        if etype == "in":
            self._entry_times.append(time.time())

    def update_dwell(self, zones, centroids, W, H):
        now = time.time()
        current_ids = {tid for tid, _, _ in centroids}
        for zone in zones:
            if zone.zone_type != "queue": continue
            for tid, cx, cy in centroids:
                in_zone = zone.contains(cx, cy, W, H)
                was_in  = tid in self._zone_entry[zone.name]
                if in_zone and not was_in:
                    self._zone_entry[zone.name][tid] = now
                elif not in_zone and was_in:
                    dwell = now - self._zone_entry[zone.name].pop(tid)
                    if dwell > 1.0:
                        self.dwell_times[zone.name].append(dwell)
                        self.dwell_log.append({"timestamp": datetime.now().isoformat(),
                                               "track_id": tid, "zone": zone.name,
                                               "dwell_sec": round(dwell, 2)})
            gone = set(self._zone_entry[zone.name]) - current_ids
            for tid in gone:
                dwell = now - self._zone_entry[zone.name].pop(tid)
                if dwell > 1.0:
                    self.dwell_times[zone.name].append(dwell)

    def get_avg_dwell(self, zone_name):
        times = self.dwell_times.get(zone_name, [])
        return round(float(np.mean(times)), 1) if times else None

    def get_entry_rate(self):
        now = time.time()
        while self._entry_times and now - self._entry_times[0] > 10.0:
            self._entry_times.popleft()
        return len(self._entry_times) / 10.0

    def update_heatmap(self, shape, centroids):
        H, W = shape[:2]
        if self.heatmap_acc is None:
            self.heatmap_acc = np.zeros((H, W), dtype=np.float32)
        for _, cx, cy in centroids:
            xi, yi = int(cx), int(cy)
            if 0 <= xi < W and 0 <= yi < H:
                self.heatmap_acc[yi, xi] += 1.0

    def update_trails(self, tid, cx, cy):
        self.trails[tid].append((int(cx), int(cy)))

    def draw_trails(self, frame):
        for _, trail in self.trails.items():
            pts = list(trail)
            for i in range(1, len(pts)):
                alpha = i / max(len(pts), 1)
                c = tuple(int(x * alpha) for x in (255, 140, 0))
                cv2.line(frame, pts[i-1], pts[i], c, 2)
        return frame

    def _flush(self):
        if self.frame_log:
            pd.DataFrame(self.frame_log).to_csv(
                f"{self.output_dir}/frame_stats.csv", index=False)
        if self.event_log:
            pd.DataFrame(self.event_log).to_csv(
                f"{self.output_dir}/events.csv", index=False)
        if self.dwell_log:
            pd.DataFrame(self.dwell_log).to_csv(
                f"{self.output_dir}/dwell_times.csv", index=False)

    def finalize(self):
        self._flush()

    def save_heatmap(self, output_path):
        if self.heatmap_acc is None or self.heatmap_acc.sum() == 0:
            return
        heat = gaussian_filter(self.heatmap_acc, sigma=40)
        norm = cv2.normalize(heat, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        hmap = cv2.applyColorMap(norm, cv2.COLORMAP_JET)
        H, W = hmap.shape[:2]
        bg   = np.zeros((H, W, 3), np.uint8) + 22
        blend = cv2.addWeighted(hmap, 0.65, bg, 0.35, 0)
        # Colorbar
        bar_h = 30
        bar   = np.zeros((bar_h, W, 3), np.uint8)
        for i in range(W):
            v = int(255 * i / W)
            bar[:, i] = cv2.applyColorMap(np.array([[v]], np.uint8), cv2.COLORMAP_JET)[0, 0]
        cv2.putText(bar, "Low", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255,255,255), 1)
        cv2.putText(bar, "High", (W-55, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255,255,255), 1)
        final = np.vstack([blend, bar])
        cv2.imwrite(output_path, final)


# ── Main processing function ──────────────────────────────────
def process_video_job(
    job_id: str,
    video_path: str,
    job_dir: str,
    config: dict,
    jobs: JobStore,
):
    """
    Full pipeline: read → detect → track → count → alert → render → save.
    Updates JobStore with live progress and frame data.
    Called in a thread pool executor from the async FastAPI handler.
    """
    try:
        from ultralytics import YOLO
        import torch

        # ── Config ──────────────────────────────────────────
        confidence     = float(config.get("confidence", 0.40))
        overcrowd_thresh = int(config.get("overcrowd_thresh", 10))
        queue_thresh   = int(config.get("queue_thresh", 6))
        sustained_sec  = int(float(config.get("sustained_sec", 30)))
        line_position  = float(config.get("line_position", 0.72))
        device         = "0" if torch.cuda.is_available() else "cpu"

        # ── Load model ───────────────────────────────────────
        jobs.update(job_id, {"status": "processing", "phase": "loading model"})
        model = YOLO("yolov8n.pt")
        dummy = np.zeros((640, 640, 3), dtype=np.uint8)
        _ = model(dummy, verbose=False, device=device)

        # ── Open video ───────────────────────────────────────
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {video_path}")

        W      = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        H      = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        FPS    = float(cap.get(cv2.CAP_PROP_FPS)) or 25.0
        TOTAL  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        jobs.update(job_id, {
            "total_frames": TOTAL,
            "resolution": f"{W}x{H}",
            "source_fps": FPS,
        })

        # ── Video writer ─────────────────────────────────────
        out_path = str(Path(job_dir) / "annotated.mp4")
        fourcc   = cv2.VideoWriter_fourcc(*"mp4v")
        writer   = cv2.VideoWriter(out_path, fourcc, FPS, (W, H))

        # ── Zones & objects ──────────────────────────────────
        vl = VirtualLine("Entrance Gate", line_position)
        zones = [
            PolygonZone("Queue Zone",
                [(0.05,0.35),(0.55,0.35),(0.55,0.70),(0.05,0.70)],
                queue_thresh, "queue"),
            PolygonZone("General Floor",
                [(0.0,0.0),(1.0,0.0),(1.0,0.70),(0.0,0.70)],
                overcrowd_thresh, "general"),
        ]
        analytics     = AnalyticsTracker(job_dir)
        email_cfg = {
            "enabled":  str(config.get("email_enabled", "false")).lower() in ("true", "1", "yes"),
            "from":     config.get("email_from", ""),
            "password": config.get("email_password", ""),
            "to":       config.get("email_to", ""),
        }
        alert_engine  = AlertEngine(str(Path(job_dir) / "alerts.csv"), email_cfg=email_cfg)

        total_in = total_out = 0
        fps_buf  = deque(maxlen=30)
        fid      = 0
        preview_every = max(1, TOTAL // 200) if TOTAL > 0 else 10

        # ── Frame loop ───────────────────────────────────────
        while True:
            t0 = time.time()
            ret, frame = cap.read()
            if not ret: break

            # Detect + track
            try:
                results = model.track(
                    frame, persist=True, classes=[0],
                    conf=confidence, iou=0.45,
                    tracker="bytetrack.yaml",
                    verbose=False, device=device,
                )
            except Exception:
                fid += 1; continue

            tracks    = []
            centroids = []
            r = results[0]
            if r.boxes is not None and r.boxes.id is not None:
                try:
                    boxes = r.boxes.xyxy.cpu().numpy().astype(int)
                    ids   = r.boxes.id.cpu().numpy().astype(int)
                    confs = r.boxes.conf.cpu().numpy()
                    for box, tid, cf in zip(boxes, ids, confs):
                        x1,y1,x2,y2 = box
                        x1,y1 = max(0,x1), max(0,y1)
                        x2,y2 = min(W-1,x2), min(H-1,y2)
                        cx,cy = (x1+x2)//2, (y1+y2)//2
                        tracks.append((int(tid),x1,y1,x2,y2,float(cf)))
                        centroids.append((int(tid),cx,cy))
                        analytics.update_trails(int(tid),cx,cy)
                except Exception:
                    pass

            # Line crossing
            for tid, cx, cy in centroids:
                ev = vl.update(tid, cx, cy, W, H)
                if ev == "in":
                    total_in += 1
                    analytics.log_event(tid,"in",vl.name,cx,cy)
                elif ev == "out":
                    total_out += 1
                    analytics.log_event(tid,"out",vl.name,cx,cy)

            # Zone occupancy
            zone_counts = {z.name: z.count_people(centroids, W, H) for z in zones}

            # Dwell time
            analytics.update_dwell(zones, centroids, W, H)
            avg_dwell  = analytics.get_avg_dwell("Queue Zone")
            entry_rate = analytics.get_entry_rate()

            # Alerts
            alert_engine.check(zones, entry_rate, sustained_sec)

            # Heatmap
            analytics.update_heatmap(frame.shape, centroids)

            # FPS
            fps_buf.append(1.0 / max(time.time() - t0, 1e-6))
            fps = float(np.mean(fps_buf))

            analytics.log_frame(fid, fps, zone_counts, total_in, total_out)
            occupancy = max(0, total_in - total_out)

            # Render
            for z in zones: z.draw(frame)
            # Counting line
            ly = int(H * line_position)
            cv2.line(frame, (0,ly),(W,ly),(0,255,100),2)
            cv2.putText(frame,f"IN:{total_in}  OUT:{total_out}",
                        (W//2-80,ly-10),cv2.FONT_HERSHEY_SIMPLEX,0.65,(0,255,100),2)
            # Trails
            frame = analytics.draw_trails(frame)
            # Boxes
            for tid,x1,y1,x2,y2,cf in tracks:
                cv2.rectangle(frame,(x1,y1),(x2,y2),(0,255,0),2)
                cv2.putText(frame,f"#{tid} {cf:.2f}",(x1,y1-6),
                            cv2.FONT_HERSHEY_SIMPLEX,0.45,(0,255,0),1)
            # HUD
            frame = draw_hud(frame, {
                "fps": fps, "live_count": len(tracks),
                "count_in": total_in, "count_out": total_out,
                "occupancy": occupancy, "entry_rate": entry_rate,
                "avg_dwell": avg_dwell, "overcrowd_thresh": overcrowd_thresh,
            })

            # Alert banners on frame
            for i, a in enumerate(alert_engine.history[-3:]):
                color = (0,0,255) if a["level"]=="CRITICAL" else (0,165,255)
                cv2.rectangle(frame,(0,H-45-(i*30)),(W,H-15-(i*30)),(15,15,15),-1)
                cv2.putText(frame,
                    f"[{a['level']}] {a['zone']}: {a['type']} ({a['value']}/{a['threshold']})",
                    (8,H-25-(i*30)),cv2.FONT_HERSHEY_SIMPLEX,0.55,color,2)

            writer.write(frame)

            # Send live update to JobStore every preview_every frames
            if fid % preview_every == 0:
                pct = int(fid / TOTAL * 100) if TOTAL > 0 else 0
                # Encode preview frame as base64
                pf = cv2.resize(frame, (640, 360))
                _, jpg = cv2.imencode(".jpg", pf, [cv2.IMWRITE_JPEG_QUALITY, 70])
                preview_b64 = base64.b64encode(jpg.tobytes()).decode()

                jobs.update(job_id, {
                    "progress":          pct,
                    "processed_frames":  fid,
                    "fps":               round(fps, 1),
                    "preview_frame":     preview_b64,
                    "frame_data": {
                        "live_count":  len(tracks),
                        "count_in":    total_in,
                        "count_out":   total_out,
                        "occupancy":   occupancy,
                        "entry_rate":  round(entry_rate, 2),
                        "avg_dwell":   avg_dwell,
                        "zone_counts": zone_counts,
                        "fps":         round(fps, 1),
                    },
                })

            fid += 1

        cap.release()
        writer.release()
        analytics.finalize()

        # Save heatmap
        heatmap_path = str(Path(job_dir) / "heatmap.png")
        analytics.save_heatmap(heatmap_path)

        # Build final stats
        all_dwell = []
        for times in analytics.dwell_times.values():
            all_dwell.extend(times)
        avg_dwell_final = round(float(np.mean(all_dwell)), 1) if all_dwell else None

        zone_summary = [
            {
                "name": z.name, "type": z.zone_type,
                "current_count": z.current_count,
                "max_count": z.max_count,
                "alert_threshold": z.alert_threshold,
            }
            for z in zones
        ]

        jobs.update(job_id, {
            "status":            "done",
            "progress":          100,
            "processed_frames":  fid,
            "preview_frame":     None,
            "stats": {
                "total_in":       total_in,
                "total_out":      total_out,
                "peak_occupancy": analytics.peak_occupancy,
                "avg_dwell_sec":  avg_dwell_final,
                "total_alerts":   len(alert_engine.history),
                "duration_sec":   round(fid / max(FPS, 1), 1),
                "resolution":     f"{W}x{H}",
                "source_fps":     round(FPS, 1),
                "total_frames":   fid,
            },
            "zones":  zone_summary,
            "alerts": alert_engine.history,
        })

    except Exception as e:
        import traceback
        jobs.update(job_id, {
            "status": "error",
            "error":  f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()[-800:]}",
        })