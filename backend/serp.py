"""
SerpAPI lookup for captured viewer snapshots.

Opt-in only: runs when /api/jobs/{job_id}/lookup/{person_id} is called, never
automatically. Uses the Google Lens engine, which needs a publicly reachable
image URL (so BACKEND_URL must be the public address of this server).
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

SERP_ENDPOINT = "https://serpapi.com/search.json"


class SerpError(Exception):
    pass


VIDEO_HOSTS = ("youtube.com", "youtu.be", "tiktok.com", "dailymotion.com", "vimeo.com")
VIDEO_PATHS = ("/reel/", "/reels/", "/video/", "/videos/", "/watch", "/shorts/")


def _get(params: dict) -> dict:
    query = urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(f"{SERP_ENDPOINT}?{query}", timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SerpError(f"SerpAPI returned HTTP {e.code}") from e
    except Exception as e:
        raise SerpError(f"SerpAPI request failed: {type(e).__name__}") from e
    if data.get("error"):
        raise SerpError(str(data["error"]))
    return data


def _is_video(link: str) -> bool:
    parts = urllib.parse.urlparse(link or "")
    host = parts.netloc.lower()
    return any(host.endswith(h) for h in VIDEO_HOSTS) or any(p in parts.path.lower() for p in VIDEO_PATHS)


def _description(key: str, token: str):
    """Fetch Google's AI overview text for a Lens search. Best effort: None on any failure."""
    try:
        data = _get({"engine": "google_ai_overview", "page_token": token, "api_key": key})
    except SerpError:
        return None
    blocks = (data.get("ai_overview") or {}).get("text_blocks") or []
    text = " ".join(b.get("snippet", "") for b in blocks if b.get("type") == "paragraph").strip()
    return text or None


def lens_lookup(image_url: str, limit: int = 60) -> dict:
    """Run a Google Lens search for image_url and return a trimmed result."""
    key = os.environ.get("SERPAPI_KEY", "").strip()
    if not key:
        raise SerpError("SERPAPI_KEY is not set on the backend")

    data = _get({"engine": "google_lens", "url": image_url, "api_key": key})

    matches = [
        {
            "title":     m.get("title"),
            "source":    m.get("source"),
            "link":      m.get("link"),
            "thumbnail": m.get("thumbnail"),
            "is_video":  _is_video(m.get("link")),
        }
        for m in (data.get("visual_matches") or [])[:limit]
    ]
    token = (data.get("ai_overview") or {}).get("page_token")
    return {
        "image_url":      image_url,
        "search_url":     (data.get("search_metadata") or {}).get("google_lens_url"),
        "description":    _description(key, token) if token else None,
        "visual_matches": matches,
        "knowledge_graph": data.get("knowledge_graph"),
    }
