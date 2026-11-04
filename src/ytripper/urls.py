"""YouTube URL helpers (F2, F3, F1).

``parse_video_id`` extracts a single video's ID (Increment 1).
``classify_url`` (Increment 3) sorts any supported link into a video,
playlist or channel and returns its canonical URL, or raises ``LinkError``
with a reason that someone who doesn't code can act on.

Pure functions only: no network and no yt-dlp import.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from urllib.parse import parse_qs, quote, unquote, urlparse

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
PLAYLIST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{2,64}$")
CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
#: YouTube handles: 3-30 letters (any script), digits, underscores, hyphens, periods or middle dots.
HANDLE_RE = re.compile(r"^@[\w.\-\u00b7]{3,30}$")
#: Legacy /c/<name> and /user/<name> channel URLs.
LEGACY_NAME_RE = re.compile(r"^[\w.\-]{1,100}$")

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
_PATH_PREFIXES = ("shorts", "live", "embed", "v")
_LEGACY_CHANNEL_PREFIXES = ("c", "user")
#: Personal lists (Watch Later, Liked videos, Liked music) only exist for a signed-in user.
_SIGN_IN_PLAYLISTS = {"WL", "LL", "LM"}
#: YouTube Mix playlists are generated per viewer and change over time.
_MIX_PREFIX = "RD"


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


# --------------------------------------------------------- link classification
class LinkKind(str, Enum):
    VIDEO = "video"
    PLAYLIST = "playlist"
    CHANNEL = "channel"


@dataclass(frozen=True)
class Link:
    """A validated YouTube link.

    Attributes:
        kind: video, playlist or channel.
        key: the video ID, the playlist ID, or the channel key
            (``@handle``, ``UC...`` channel ID, ``c/<name>`` or ``user/<name>``).
        url: canonical URL to hand to yt-dlp.
    """

    kind: LinkKind
    key: str
    url: str


class LinkError(ValueError):
    """A link that YTripper can't use; ``str(exc)`` is the plain-language reason."""


def canonical_playlist_url(playlist_id: str) -> str:
    """Return the canonical URL for a validated playlist ID."""
    if not PLAYLIST_ID_RE.fullmatch(playlist_id):
        raise ValueError(f"invalid playlist id: {playlist_id!r}")
    return f"https://www.youtube.com/playlist?list={playlist_id}"


def canonical_channel_url(key: str) -> str:
    """Return the canonical URL for a channel key produced by ``classify_url``."""
    if HANDLE_RE.fullmatch(key):
        return "https://www.youtube.com/" + quote(key, safe="@")
    if CHANNEL_ID_RE.fullmatch(key):
        return f"https://www.youtube.com/channel/{key}"
    prefix, _, name = key.partition("/")
    if prefix in _LEGACY_CHANNEL_PREFIXES and LEGACY_NAME_RE.fullmatch(name):
        return f"https://www.youtube.com/{prefix}/{quote(name)}"
    raise ValueError(f"invalid channel key: {key!r}")


def _with_scheme(text: str) -> str:
    """Add ``https://`` to a pasted YouTube link that lacks it (``youtube.com/@x``)."""
    if "://" in text:
        return text
    host = text.split("/", 1)[0].lower()
    if host in _YOUTUBE_HOSTS or host in _SHORT_HOSTS:
        return "https://" + text
    return text


def _classify_playlist(query: str) -> Link:
    playlist_id = (parse_qs(query).get("list") or [""])[0]
    if playlist_id in _SIGN_IN_PLAYLISTS:
        raise LinkError("Watch Later and Liked lists need a sign-in, which YTripper never uses")
    if playlist_id.startswith(_MIX_PREFIX):
        raise LinkError("YouTube Mix playlists are generated automatically and can't be backed up")
    if not PLAYLIST_ID_RE.fullmatch(playlist_id):
        raise LinkError("the playlist ID in this link is not valid")
    return Link(LinkKind.PLAYLIST, playlist_id, canonical_playlist_url(playlist_id))


def _classify_channel(parts: list[str]) -> Link | None:
    """Channel link from decoded path parts, or None if the path is not a channel."""
    first = parts[0]
    if first.startswith("@"):
        if not HANDLE_RE.fullmatch(first):
            raise LinkError("the channel handle in this link is not valid")
        key = first
    elif first == "channel":
        if len(parts) < 2 or not CHANNEL_ID_RE.fullmatch(parts[1]):
            raise LinkError("the channel ID in this link is not valid")
        key = parts[1]
    elif first in _LEGACY_CHANNEL_PREFIXES:
        if len(parts) < 2 or not LEGACY_NAME_RE.fullmatch(parts[1]):
            raise LinkError("the channel name in this link is not valid")
        key = f"{first}/{parts[1]}"
    else:
        return None
    # Anything after the channel key (/videos, /shorts, /streams, /playlists, ...) is a tab: ignored.
    return Link(LinkKind.CHANNEL, key, canonical_channel_url(key))


def classify_url(text: str) -> Link:
    """Classify a YouTube link as a video, playlist or channel.

    A watch link that also carries ``&list=`` is treated as the single video.

    Raises:
        LinkError: with a plain-language reason when the link can't be used.
    """
    text = (text or "").strip()
    if not text:
        raise LinkError("the line is empty")
    text = _with_scheme(text)
    try:
        parsed = urlparse(text)
        host = (parsed.hostname or "").lower()
    except ValueError:
        raise LinkError("this is not a valid web link") from None
    if parsed.scheme not in ("http", "https"):
        raise LinkError("this is not a web link (it should start with https://)")
    if host not in _YOUTUBE_HOSTS and host not in _SHORT_HOSTS:
        raise LinkError("this is not a YouTube link")

    video_id = parse_video_id(text)
    if video_id:
        return Link(LinkKind.VIDEO, video_id, canonical_video_url(video_id))

    parts = [unquote(p) for p in parsed.path.split("/") if p]
    if host in _SHORT_HOSTS or parts[:1] == ["watch"] or (len(parts) >= 1 and parts[0] in _PATH_PREFIXES):
        raise LinkError("the video ID in this link is not valid")
    if parts[:1] == ["playlist"]:
        return _classify_playlist(parsed.query)
    if parts:
        channel = _classify_channel(parts)
        if channel:
            return channel
    raise LinkError("unsupported YouTube link: use a video, playlist or channel (@handle) link")
