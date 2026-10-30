"""
Storefront Engagement FastAPI Backend
=====================================
Exposes the YOLOv8-pose + ByteTrack visitor attention pipeline as a REST API
with Server-Sent Events (SSE) for real-time progress streaming.

Routes:
  POST /api/analyze          – Upload video, start job, return job_id
  GET  /api/status/{job_id}  – Poll job status (JSON)
  GET  /api/stream/{job_id}  – SSE stream of live frame data
  GET  /api/jobs             – List all jobs (one row per uploaded video)
  DELETE /api/jobs/{job_id}  – Delete a job and its files
  GET  /api/download/{job_id}/{file} – Download results
  GET  /health               – Health check
"""

import asyncio
import base64
import io
import json
import os
import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

def _load_env_file():
    """Read backend/.env into os.environ (real environment variables win)."""
    path = Path(__file__).with_name(".env")
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env_file()

# Import the processing pipeline
from processor import process_video_job, JobStore
import meta
import serp

# ── App setup ─────────────────────────────────────────────────
app = FastAPI(
    title="Storefront Engagement API",
    description="Visitor attention analysis for prerecorded video",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # In production: set to your Vercel URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global job store (in-memory; for production use Redis)
jobs = JobStore()

# Output base directory
OUTPUT_BASE = Path(os.environ.get("OUTPUT_DIR", "/tmp/crowdvision_output"))
OUTPUT_BASE.mkdir(parents=True, exist_ok=True)

# Fields kept in <job_dir>/job.json so past jobs survive a restart
_PERSIST_SKIP = {"preview_frame", "frame_data"}


def _save_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return
    data = {k: v for k, v in job.items() if k not in _PERSIST_SKIP}
    (Path(job["job_dir"]) / "job.json").write_text(json.dumps(data), encoding="utf-8")


def _load_jobs():
    """Reload finished jobs from disk; a job that was mid-run at shutdown is marked as failed."""
    for meta in OUTPUT_BASE.glob("*/job.json"):
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            if data.get("status") not in ("done", "error"):
                data["status"], data["error"] = "error", "Interrupted by a server restart"
            jobs.create(meta.parent.name, data)
        except Exception:
            continue


_load_jobs()


# ── Routes ────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check endpoint."""
    try:
        import torch
        import ultralytics
        gpu = torch.cuda.is_available()
        return {
            "status": "ok",
            "gpu": gpu,
            "device": "cuda" if gpu else "cpu",
            "ultralytics": ultralytics.__version__,
            "torch": torch.__version__,
        }
    except Exception as e:
        return {"status": "ok", "note": str(e)}


@app.post("/api/analyze")
async def analyze_video(
    video: UploadFile = File(...),
    config: str = Form(default="{}"),
):
    """
    Upload a video file and start analysis.
    Returns a job_id for tracking progress.
    """
    # Validate file type
    allowed = {
        "video/mp4", "video/avi", "video/x-msvideo",
        "video/quicktime", "video/x-matroska", "video/webm",
        "application/octet-stream",  # some browsers send this for video
    }
    if video.content_type and video.content_type not in allowed:
        # Try extension check as fallback
        ext = Path(video.filename or "").suffix.lower()
        if ext not in {".mp4", ".avi", ".mov", ".mkv", ".webm"}:
            raise HTTPException(400, detail=f"Unsupported file type: {video.content_type}")

    # Parse config
    try:
        cfg = json.loads(config)
    except Exception:
        cfg = {}

    # Create job
    job_id = str(uuid.uuid4())[:8]
    job_dir = OUTPUT_BASE / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    # Save uploaded video
    video_path = job_dir / f"input{Path(video.filename or 'video.mp4').suffix}"
    with open(video_path, "wb") as f:
        content = await video.read()
        f.write(content)

    file_mb = len(content) / 1e6

    # Initialise job record
    jobs.create(job_id, {
        "status": "queued",
        "progress": 0,
        "total_frames": 0,
        "processed_frames": 0,
        "fps": 0.0,
        "video_path": str(video_path),
        "job_dir": str(job_dir),
        "config": cfg,
        "file_mb": round(file_mb, 1),
        "filename": video.filename or "video",
        "created_at": time.time(),
    })

    # Start background processing
    asyncio.create_task(run_processing(job_id, str(video_path), job_dir, cfg))

    return {"job_id": job_id, "status": "queued", "file_mb": round(file_mb, 1)}


async def run_processing(job_id: str, video_path: str, job_dir: Path, config: dict):
    """Run the CV pipeline in a background task."""
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None,
            process_video_job,
            job_id, video_path, str(job_dir), config, jobs
        )
    except Exception as e:
        jobs.update(job_id, {"status": "error", "error": str(e)})
    _save_job(job_id)


@app.get("/api/jobs")
async def list_jobs():
    """One summary row per uploaded video, newest first."""
    rows = []
    for job_id, job in jobs.all().items():
        viewers = job.get("viewers") or []
        stats = job.get("stats") or {}
        rows.append({
            "job_id":       job_id,
            "filename":     job.get("filename", "video"),
            "created_at":   job.get("created_at", 0),
            "status":       job.get("status", "queued"),
            "progress":     job.get("progress", 0),
            "file_mb":      job.get("file_mb", 0),
            "duration_sec": stats.get("duration_sec"),
            "viewers":      len(viewers),
            "engaged":      sum(1 for v in viewers if v.get("behaviour") == "engaged"),
            "strong":       sum(1 for v in viewers if v.get("behaviour") == "strong"),
            "error":        job.get("error"),
        })
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    return rows


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    """Remove a job record and every file it produced."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, detail="Job not found")
    if job.get("status") in ("queued", "processing"):
        raise HTTPException(409, detail="Job is still processing")
    job_dir = Path(job["job_dir"]).resolve()
    if OUTPUT_BASE.resolve() in job_dir.parents:
        shutil.rmtree(job_dir, ignore_errors=True)
    jobs.delete(job_id)
    return {"deleted": job_id}


@app.post("/api/jobs/{job_id}/lookup/{person_id}")
async def lookup_person(job_id: str, person_id: int):
    """Run a SerpAPI Google Lens search on one captured snapshot and cache the result."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, detail="Job not found")
    job_dir = Path(job["job_dir"])
    if not (job_dir / "captures" / f"person_{person_id}.jpg").is_file():
        raise HTTPException(404, detail="No snapshot for that person")

    be_url = (os.environ.get("PUBLIC_URL") or os.environ.get("BACKEND_URL", "http://localhost:8000")).rstrip("/")
    if "localhost" in be_url or "127.0.0.1" in be_url:
        raise HTTPException(400, detail="Set PUBLIC_URL to a public tunnel/server URL so SerpAPI can fetch the snapshot")

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None, serp.lens_lookup, f"{be_url}/api/file/{job_id}/captures/person_{person_id}.jpg")
    except serp.SerpError as e:
        raise HTTPException(502, detail=str(e))

    out_dir = job_dir / "lookups"
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"person_{person_id}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


@app.post("/api/jobs/{job_id}/lookup/{person_id}/meta/{index}")
async def lookup_match_meta(job_id: str, person_id: int, index: int):
    """Fetch public metadata (account, caption, date) for one saved Lens match and cache it.

    Only links already saved in the lookup are fetched, never a URL supplied by the client."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, detail="Job not found")
    path = Path(job["job_dir"]) / "lookups" / f"person_{person_id}.json"
    if not path.is_file():
        raise HTTPException(404, detail="No lookup yet")
    doc = json.loads(path.read_text(encoding="utf-8"))
    matches = doc.get("visual_matches") or []
    if not 0 <= index < len(matches):
        raise HTTPException(404, detail="No such match")
    if not matches[index].get("meta"):
        loop = asyncio.get_event_loop()
        matches[index]["meta"] = await loop.run_in_executor(None, meta.page_metadata, matches[index]["link"])
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return matches[index]["meta"]


@app.get("/api/jobs/{job_id}/lookup/{person_id}")
async def get_lookup(job_id: str, person_id: int):
    """Return the cached SerpAPI result for a snapshot, or null if none was run yet."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, detail="Job not found")
    path = Path(job["job_dir"]) / "lookups" / f"person_{person_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    """Get current job status (poll endpoint)."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, detail="Job not found")
    return _build_response(job_id, job)


@app.get("/api/stream/{job_id}")
async def stream_status(job_id: str):
    """
    Server-Sent Events stream for real-time job updates.
    Frontend connects here and receives JSON updates every ~0.5s.
    """
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, detail="Job not found")

    async def event_generator():
        last_frame = -1
        timeout_start = time.time()
        max_wait = 600  # 10 minutes max

        while True:
            job = jobs.get(job_id)
            if not job:
                break

            current_frame = job.get("processed_frames", 0)
            status = job.get("status", "queued")

            # Send update if frame changed OR status changed
            if current_frame != last_frame or status in ("done", "error"):
                last_frame = current_frame
                data = json.dumps(_build_response(job_id, job))
                yield f"data: {data}\n\n"
                timeout_start = time.time()  # reset timeout

            if status in ("done", "error"):
                break

            # Safety timeout
            if time.time() - timeout_start > max_wait:
                yield f"data: {json.dumps({'status': 'error', 'error': 'Processing timed out'})}\n\n"
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/download/{job_id}/{file_type}")
async def download_file(job_id: str, file_type: str, request: Request):
    """
    Download a result file.
    Video uses HTTP Range requests so <video> can seek without full download.
    """
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, detail="Job not found")
    if job.get("status") != "done":
        raise HTTPException(400, detail="Job not complete yet")

    job_dir = Path(job["job_dir"])

    if file_type == "zip":
        zip_path = job_dir / "results.zip"
        if not zip_path.exists():
            _build_zip(job_id, job_dir, job.get("filename", "video"))
        return FileResponse(str(zip_path), filename=f"storefront_{job_id}.zip",
                            media_type="application/zip",
                            headers={"Access-Control-Allow-Origin": "*"})

    original = next(iter(sorted(job_dir.glob("input.*"))), job_dir / "input.mp4")
    file_map = {
        "video":    (job_dir / "annotated.mp4",  "video/mp4"),
        "original": (original, {".webm": "video/webm", ".mov": "video/quicktime", ".mkv": "video/x-matroska",
                                ".avi": "video/x-msvideo"}.get(original.suffix.lower(), "video/mp4")),
        "csv":      (job_dir / "viewers.csv",      "text/csv"),
    }
    item = file_map.get(file_type)
    if not item:
        raise HTTPException(404, detail="Unknown file type")

    path, media_type = item
    if not path.exists():
        raise HTTPException(404, detail=f"{file_type} not found — processing may not have completed yet")

    file_size = path.stat().st_size

    # Range request support — required for browser <video> tag seek/stream
    range_header = request.headers.get("range")
    if range_header and file_type in ("video", "original"):
        try:
            range_val = range_header.replace("bytes=", "")
            parts = range_val.split("-")
            start = int(parts[0])
            end   = int(parts[1]) if parts[1] else file_size - 1
        except Exception:
            start, end = 0, file_size - 1
        end    = min(end, file_size - 1)
        length = end - start + 1

        def iter_range():
            with open(path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    data = f.read(min(65536, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        return StreamingResponse(
            iter_range(), status_code=206, media_type=media_type,
            headers={
                "Content-Range":               f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges":               "bytes",
                "Content-Length":              str(length),
                "Access-Control-Allow-Origin": "*",
                "Cache-Control":               "no-cache",
            },
        )

    return FileResponse(str(path), media_type=media_type,
        headers={
            "Accept-Ranges":               "bytes",
            "Content-Length":              str(file_size),
            "Access-Control-Allow-Origin": "*",
            "Cache-Control":               "no-cache",
        })


@app.get("/api/file/{job_id}/{filename:path}")
async def get_named_file(job_id: str, filename: str):
    """Serve a file from the job directory (CSV, JSON, captured snapshots)."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, detail="Job not found")
    job_dir = Path(job["job_dir"]).resolve()
    path = (job_dir / filename).resolve()
    if job_dir not in path.parents or not path.is_file():  # stay inside the job folder
        raise HTTPException(404, detail="File not found")
    return FileResponse(str(path))


# ── Helpers ───────────────────────────────────────────────────

def _build_response(job_id: str, job: dict) -> dict:
    """Build the response dict for a job."""
    job_dir = Path(job.get("job_dir", ""))
    be_url = os.environ.get("BACKEND_URL", "http://localhost:8000")

    resp = {
        "job_id":            job_id,
        "status":            job.get("status", "queued"),
        "progress":          job.get("progress", 0),
        "total_frames":      job.get("total_frames", 0),
        "processed_frames":  job.get("processed_frames", 0),
        "fps":               job.get("fps", 0.0),
        "frame_data":        job.get("frame_data"),
        "preview_frame":     job.get("preview_frame"),
        "error":             job.get("error"),
        "filename":          job.get("filename"),
        "created_at":        job.get("created_at"),
    }

    if job.get("status") == "done":
        resp["stats"]  = job.get("stats")
        resp["viewers"] = job.get("viewers")
        resp["annotated_video_url"] = f"{be_url}/api/download/{job_id}/video"
        resp["viewers_url"]         = f"{be_url}/api/file/{job_id}/viewers.csv"
        if (job_dir / "captures" / "engaged.json").exists():
            resp["engaged_json_url"] = f"{be_url}/api/file/{job_id}/captures/engaged.json"

    return resp


def _build_zip(job_id: str, job_dir: Path, video_name: str):
    """Create a ZIP of all result files."""
    zip_path = job_dir / "results.zip"
    files_to_include = ["annotated.mp4", "viewers.csv"]
    cap_dir = job_dir / "captures"
    if cap_dir.is_dir():
        files_to_include += [f"captures/{f.name}" for f in sorted(cap_dir.iterdir()) if f.is_file()]
    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in files_to_include:
            fpath = job_dir / fname
            if fpath.exists():
                zf.write(str(fpath), arcname=f"storefront_{job_id}/{fname}")
