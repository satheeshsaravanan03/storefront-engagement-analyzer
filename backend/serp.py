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


def lens_lookup(image_url: str, limit: int = 10) -> dict:
    """Run a Google Lens search for image_url and return a trimmed result."""
    key = os.environ.get("SERPAPI_KEY", "").strip()
    if not key:
        raise SerpError("SERPAPI_KEY is not set on the backend")

    query = urllib.parse.urlencode({"engine": "google_lens", "url": image_url, "api_key": key})
    try:
        with urllib.request.urlopen(f"{SERP_ENDPOINT}?{query}", timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SerpError(f"SerpAPI returned HTTP {e.code}") from e
    except Exception as e:
        raise SerpError(f"SerpAPI request failed: {e}") from e

    if data.get("error"):
        raise SerpError(str(data["error"]))

    matches = [
        {
            "title":     m.get("title"),
            "source":    m.get("source"),
            "link":      m.get("link"),
            "thumbnail": m.get("thumbnail"),
        }
        for m in (data.get("visual_matches") or [])[:limit]
    ]
    return {
        "image_url":      image_url,
        "search_url":     (data.get("search_metadata") or {}).get("google_lens_url"),
        "visual_matches": matches,
        "knowledge_graph": data.get("knowledge_graph"),
    }
