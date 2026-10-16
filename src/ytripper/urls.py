"""YouTube URL helpers.

Increment 1 needs only single-video ID extraction. Full input validation
(playlists, channels, line-numbered errors) is added in Increment 3.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
_PATH_PREFIXES = ("shorts", "live", "embed", "v")


def is_video_id(value: str) -> bool:
    """Return True if *value* is a syntactically valid 11-character video ID."""
    return bool(VIDEO_ID_RE.fullmatch(value))


def parse_video_id(url: str) -> str | None:
    """Extract the video ID from a YouTube video URL, or return None.

    Accepts ``youtu.be/<id>``, ``youtube.com/watch?v=<id>`` and
    ``youtube.com/{shorts,live,embed,v}/<id>``; tracking parameters such as
    ``?si=`` are ignored. Only YouTube hosts over http(s) are accepted.
    """
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    parts = [p for p in parsed.path.split("/") if p]

    candidate: str | None = None
    if host in _SHORT_HOSTS:
        candidate = parts[0] if parts else None
    elif host in _YOUTUBE_HOSTS:
        if parts[:1] == ["watch"]:
            candidate = (parse_qs(parsed.query).get("v") or [None])[0]
        elif len(parts) >= 2 and parts[0] in _PATH_PREFIXES:
            candidate = parts[1]
    return candidate if candidate and is_video_id(candidate) else None


def canonical_video_url(video_id: str) -> str:
    """Return the canonical watch URL for a validated video ID."""
    if not is_video_id(video_id):
        raise ValueError(f"invalid video id: {video_id!r}")
    return f"https://www.youtube.com/watch?v={video_id}"
