"""
Storefront Engagement FastAPI Backend
=====================================
Exposes the YOLOv8-pose + ByteTrack visitor attention pipeline as a REST API
with Server-Sent Events (SSE) for real-time progress streaming.

Routes:
  POST /api/analyze          – Upload video, start job, return job_id
  GET  /api/status/{job_id}  – Poll job status (JSON)
  GET  /api/stream/{job_id}  – SSE stream of live frame data
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

# Import the processing pipeline
from processor import process_video_job, JobStore

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

    file_map = {
        "video":   (job_dir / "annotated.mp4",  "video/mp4"),
        "csv":     (job_dir / "viewers.csv",      "text/csv"),
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
    if range_header and file_type == "video":
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


@app.get("/api/file/{job_id}/{filename}")
async def get_named_file(job_id: str, filename: str):
    """Serve any named file from job directory (for CSV downloads)."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, detail="Job not found")
    path = Path(job["job_dir"]) / Path(filename).name
    if not path.exists():
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
    }

    if job.get("status") == "done":
        resp["stats"]  = job.get("stats")
        resp["viewers"] = job.get("viewers")
        resp["annotated_video_url"] = f"{be_url}/api/download/{job_id}/video"
        resp["viewers_url"]         = f"{be_url}/api/file/{job_id}/viewers.csv"

    return resp


def _build_zip(job_id: str, job_dir: Path, video_name: str):
    """Create a ZIP of all result files."""
    zip_path = job_dir / "results.zip"
    files_to_include = ["annotated.mp4", "viewers.csv"]
    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in files_to_include:
            fpath = job_dir / fname
            if fpath.exists():
                zf.write(str(fpath), arcname=f"storefront_{job_id}/{fname}")
