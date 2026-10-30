"""
Public metadata (account/channel, caption, publish date) for a page returned by the Lens search.

Uses the same sources a link preview does: the platform's oEmbed endpoint where one is
open (YouTube, TikTok, X, Vimeo, Dailymotion), otherwise the page's Open Graph tags.
No logins and no API credits. Sites that hide this from anonymous visitors (often
Instagram and Facebook) simply return less.
"""

import ipaddress
import json
import socket
import urllib.parse
import urllib.request
from html.parser import HTMLParser

UA = "Mozilla/5.0 (compatible; StorefrontEngagementBot/1.0)"
MAX_BYTES = 1_500_000

OEMBED = {
    "youtube.com":     "https://www.youtube.com/oembed?format=json&url={u}",
    "youtu.be":        "https://www.youtube.com/oembed?format=json&url={u}",
    "tiktok.com":      "https://www.tiktok.com/oembed?url={u}",
    "x.com":           "https://publish.twitter.com/oembed?omit_script=1&url={u}",
    "twitter.com":     "https://publish.twitter.com/oembed?omit_script=1&url={u}",
    "vimeo.com":       "https://vimeo.com/api/oembed.json?url={u}",
    "dailymotion.com": "https://www.dailymotion.com/services/oembed?format=json&url={u}",
}

PLATFORMS = {
    "youtube.com": "YouTube", "youtu.be": "YouTube", "instagram.com": "Instagram",
    "facebook.com": "Facebook", "fb.watch": "Facebook", "tiktok.com": "TikTok",
    "x.com": "X", "twitter.com": "X", "threads.com": "Threads", "threads.net": "Threads",
    "reddit.com": "Reddit", "pinterest.com": "Pinterest", "snapchat.com": "Snapchat",
    "vimeo.com": "Vimeo", "dailymotion.com": "Dailymotion", "tenor.com": "Tenor",
}


def _match_host(host: str, table: dict):
    host = host.lower().removeprefix("www.")
    for h, v in table.items():
        if host == h or host.endswith("." + h):
            return v
    return None


def _safe_url(url: str) -> bool:
    """http(s) only, and never an address on the local machine or a private network."""
    parts = urllib.parse.urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    try:
        for info in socket.getaddrinfo(parts.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
    except OSError:
        return False
    return True


def _fetch(url: str, timeout: int = 10) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(MAX_BYTES), r.headers.get_content_charset() or "utf-8"


class _Tags(HTMLParser):
    """Collect <meta> tags and the <title>."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and a.get("content"):
            k = a.get("property") or a.get("name") or a.get("itemprop")
            if k:
                self.meta.setdefault(k.lower(), a["content"].strip())
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def _opengraph(url: str) -> dict:
    body, charset = _fetch(url)
    p = _Tags()
    p.feed(body.decode(charset, errors="replace"))
    m = p.meta
    return {
        "title":       m.get("og:title") or p.title.strip() or None,
        "description": m.get("og:description") or m.get("description"),
        "author":      m.get("article:author") or m.get("author") or m.get("profile:username"),
        "published":   (m.get("article:published_time") or m.get("datepublished")
                        or m.get("video:release_date") or m.get("uploaddate") or m.get("date")),
        "image":       m.get("og:image"),
        "site_name":   m.get("og:site_name"),
    }


def _oembed(endpoint: str, url: str) -> dict:
    body, charset = _fetch(endpoint.format(u=urllib.parse.quote(url, safe="")))
    d = json.loads(body.decode(charset, errors="replace"))
    return {
        "title":      d.get("title"),
        "author":     d.get("author_name"),
        "author_url": d.get("author_url"),
        "image":      d.get("thumbnail_url"),
        "site_name":  d.get("provider_name"),
    }


def page_metadata(url: str) -> dict:
    """Best-effort public metadata for url. Never raises; 'found' says whether anything came back."""
    host = urllib.parse.urlparse(url).hostname or ""
    out = {"url": url, "platform": _match_host(host, PLATFORMS) or host.removeprefix("www."),
           "title": None, "author": None, "author_url": None, "description": None,
           "published": None, "image": None, "source": None, "found": False}
    if not _safe_url(url):
        out["error"] = "URL not allowed"
        return out

    endpoint = _match_host(host, OEMBED)
    if endpoint:
        try:
            out.update({k: v for k, v in _oembed(endpoint, url).items() if v})
            out["source"] = "oembed"
        except Exception:
            pass

    try:  # Open Graph fills in what oEmbed lacks (description, publish date) or stands in for it
        for k, v in _opengraph(url).items():
            if v and not out.get(k):
                out[k] = v
        out["source"] = out["source"] or "opengraph"
    except Exception:
        if not out["source"]:
            out["error"] = "Page could not be read (blocked or login required)"

    out["found"] = any(out[k] for k in ("title", "author", "description", "published"))
    return out
