"""
faces.py
========
Matches the snapshot of each engaged viewer against a registry of people who
registered with their photo, so a viewer can be shown with their name and
contact details.

Only the FACE is compared, never clothes or background:

  1. YuNet finds the face and its five landmarks (eyes, nose, mouth corners).
  2. SFace aligns the face on those landmarks and turns it into a 128-number
     embedding (cosine similarity is the distance).
  3. The embedding is compared with the embedding of every registered photo.

Both models ship with OpenCV (no extra Python packages); the two .onnx files
are downloaded once into backend/models/. `embed` is the only part that has to
change to plug in a stronger model (e.g. ArcFace) later.

A match is deliberately conservative:
  * "matched"   score >= MATCH and it beats the runner-up by MARGIN
  * "possible"  score >= POSSIBLE (shown as a suggestion to confirm)
  * "unmatched" a face was found but nobody in the registry resembles it
  * "no_face"   no usable face in the snapshot
"""

import json
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np

HERE = Path(__file__).parent
MODELS_DIR = HERE / "models"
REGISTRY_DIR = HERE / "registry"
REGISTRY_FILE = REGISTRY_DIR / "profiles.json"
PHOTOS_DIR = REGISTRY_DIR / "photos"

_MODEL_URLS = {
    "yunet.onnx": "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "sface.onnx": "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
}

MATCH = 0.45      # cosine similarity for a confident match (OpenCV's same-person cut-off is 0.363)
POSSIBLE = 0.363  # below this the face is treated as nobody in the registry
MARGIN = 0.05     # the best match must beat the second best by this much to be called "matched"
MIN_FACE = 28     # px; smaller faces are too coarse to compare
TOP_N = 3

_detector = None
_recognizer = None
_cache: Dict[str, tuple] = {}   # photo path -> (mtime, embedding or None, face width)


def _ensure_models():
    MODELS_DIR.mkdir(exist_ok=True)
    for name, url in _MODEL_URLS.items():
        path = MODELS_DIR / name
        if not path.is_file():
            tmp = path.with_suffix(".part")
            urllib.request.urlretrieve(url, tmp)
            tmp.replace(path)


def _load():
    global _detector, _recognizer
    if _detector is None:
        _ensure_models()
        _detector = cv2.FaceDetectorYN.create(str(MODELS_DIR / "yunet.onnx"), "", (320, 320), 0.7, 0.3, 5000)
        _recognizer = cv2.FaceRecognizerSF.create(str(MODELS_DIR / "sface.onnx"), "")


def _best_face(img: np.ndarray) -> Optional[np.ndarray]:
    """The most prominent face (large and confident), as a YuNet row, or None."""
    _load()
    h, w = img.shape[:2]
    # tiny crops are upscaled so the detector has something to work with
    scale = 1.0
    if max(h, w) < 320:
        scale = 320 / max(h, w)
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        h, w = img.shape[:2]
    _detector.setInputSize((w, h))
    _, faces = _detector.detect(img)
    if faces is None or len(faces) == 0:
        return None
    best = max(faces, key=lambda f: float(f[14]) * float(f[2]) * float(f[3]))
    best = best.copy()
    best[:14] /= scale   # back to the coordinates of the original image
    return best


def embed(img: np.ndarray):
    """-> (unit-length embedding, face width in px) for the main face in `img`, or (None, 0)."""
    face = _best_face(img)
    if face is None or float(face[2]) < MIN_FACE:
        return None, 0
    # SFace is run on the original pixels with landmarks in original coordinates
    aligned = _recognizer.alignCrop(img, face)
    feat = _recognizer.feature(aligned).flatten().astype(np.float32)
    norm = float(np.linalg.norm(feat))
    return (feat / norm if norm else None), int(face[2])


def _score(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


# ── registry ─────────────────────────────────────────────────

def load_profiles() -> List[dict]:
    """Registered people with the state of their photo; embeddings are cached per file."""
    try:
        raw = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for p in raw.get("profiles", []):
        item = {k: p.get(k) for k in ("id", "name", "email", "phone", "role", "company", "notes")}
        item["photo"] = p.get("photo")
        item["embedding"], item["photo_status"], item["face_px"] = _photo_embedding(p.get("photo"))
        out.append(item)
    return out


def _photo_embedding(name: Optional[str]):
    if not name:
        return None, "no_photo", 0
    path = (PHOTOS_DIR / name).resolve()
    if PHOTOS_DIR.resolve() not in path.parents or not path.is_file():
        return None, "missing", 0
    mtime = path.stat().st_mtime
    hit = _cache.get(str(path))
    if not hit or hit[0] != mtime:
        img = cv2.imread(str(path))
        emb, px = embed(img) if img is not None else (None, 0)
        hit = _cache[str(path)] = (mtime, emb, px)
    return hit[1], ("ok" if hit[1] is not None else "no_face"), hit[2]


def public_profile(p: dict) -> dict:
    """A profile without its embedding, safe to send to the UI."""
    return {k: v for k, v in p.items() if k != "embedding"}


# ── matching ─────────────────────────────────────────────────

def match_image(img: np.ndarray, profiles: List[dict]) -> dict:
    """Compare one snapshot with every registered face."""
    emb, px = embed(img)
    if emb is None:
        return {"status": "no_face", "score": None, "profile_id": None, "face_px": px, "candidates": []}
    ranked = sorted(
        ({"profile_id": p["id"], "score": round(_score(emb, p["embedding"]), 3)}
         for p in profiles if p["embedding"] is not None),
        key=lambda c: c["score"], reverse=True)
    if not ranked or ranked[0]["score"] < POSSIBLE:
        return {"status": "unmatched", "score": ranked[0]["score"] if ranked else None,
                "profile_id": None, "face_px": px, "candidates": ranked[:TOP_N]}
    best = ranked[0]
    runner_up = ranked[1]["score"] if len(ranked) > 1 else -1.0
    confident = best["score"] >= MATCH and best["score"] - runner_up >= MARGIN
    return {"status": "matched" if confident else "possible", "score": best["score"],
            "profile_id": best["profile_id"], "face_px": px, "candidates": ranked[:TOP_N]}


def identify_job(job_dir: Path) -> dict:
    """Match every captured snapshot of a finished job against the registry."""
    profiles = load_profiles()
    people = []
    for f in sorted((job_dir / "captures").glob("person_*.jpg"),
                    key=lambda p: int(p.stem.split("_")[1])):
        img = cv2.imread(str(f))
        res = match_image(img, profiles) if img is not None else \
            {"status": "no_face", "score": None, "profile_id": None, "face_px": 0, "candidates": []}
        people.append({"person_id": int(f.stem.split("_")[1]), "image": f"captures/{f.name}", **res})
    doc = {
        "registry_size": len(profiles),
        "with_photo": sum(1 for p in profiles if p["embedding"] is not None),
        "thresholds": {"match": MATCH, "possible": POSSIBLE, "margin": MARGIN},
        "people": people,
    }
    (job_dir / "identities.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc
