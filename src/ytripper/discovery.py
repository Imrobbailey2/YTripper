"""Find the videos behind each link (F1, F1a, F1b, F1c, F2, F3, F4a).

Increment 3, step 2. Channel and playlist links are expanded into video IDs
with yt-dlp used as a library (decision 1) in *flat* mode: only the listing
pages are read, nothing is downloaded, and no cookies or credentials are ever
passed (NF4). A single video link needs no network at all.

- A channel is read tab by tab: Videos, Shorts and Live (past livestreams)
  (F1a). A tab the channel doesn't have is treated as empty.
- Upcoming and currently live streams are skipped as "not yet available" (F1b).
- Members-only, paid and other sign-in videos are skipped as "requires
  sign-in" (F1c); the rest of the run continues.
- Private and deleted entries in a playlist are skipped as "unavailable".
- A video found through several links is listed once, with every place it was
  found (F4a).
- If YouTube asks to "confirm you're not a bot", discovery stops at once and
  the result is marked ``blocked`` so the caller can save and exit (NF11b).

Reading the channel's own public playlists (F14, F14a) is step 3. Details that
flat listings don't include (e.g. upload dates on channel tabs) are filled in
by the preview (Increment 4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Iterable

from .downloader import _YtdlpLogger, ensure_tools_on_path
from .logging_setup import get_logger
from .urls import Link, LinkKind, canonical_video_url, is_video_id

log = get_logger("discovery")

#: Channel tabs read for a channel link, with the name shown to the user (F1a).
CHANNEL_TABS: dict[str, str] = {"videos": "Videos", "shorts": "Shorts", "streams": "Live"}

SKIP_NOT_YET_AVAILABLE = "not yet available"
SKIP_REQUIRES_SIGN_IN = "requires sign-in"
SKIP_UNAVAILABLE = "unavailable (private or deleted)"

#: yt-dlp ``live_status`` values for streams that have no recording yet (F1b).
_NOT_YET_LIVE_STATUSES = {"is_upcoming", "is_live"}
#: yt-dlp ``availability`` values that need an account (F1c).
_SIGN_IN_AVAILABILITY = {"subscriber_only", "premium_only", "needs_auth"}
#: Titles YouTube shows for playlist entries that can no longer be watched.
_UNAVAILABLE_TITLES = {"[private video]", "[deleted video]"}


# ------------------------------------------------------------------- records
class SourceKind(str, Enum):
    CHANNEL = "channel"
    PLAYLIST = "playlist"
    LINK = "link"


@dataclass(frozen=True)
class Source:
    """Where a video was found.

    Attributes:
        kind: channel, playlist or a direct video link.
        key: the channel key, playlist ID or video ID from the link.
        tab: for a channel: videos, shorts or streams.
        title: playlist or channel title, when YouTube gave one.
    """

    kind: SourceKind
    key: str
    tab: str = ""
    title: str = ""

    def __str__(self) -> str:
        if self.kind is SourceKind.CHANNEL:
            return f"channel {self.title or self.key} ({CHANNEL_TABS.get(self.tab, self.tab)})"
        if self.kind is SourceKind.PLAYLIST:
            return f"playlist {self.title!r} ({self.key})" if self.title else f"playlist {self.key}"
        return "video link"


@dataclass
class FoundVideo:
    """One video to back up (or to skip, with the reason)."""

    video_id: str
    url: str
    title: str | None = None
    duration_s: float | None = None
    #: YYYYMMDD when the listing provides it.
    upload_date: str | None = None
    channel: str | None = None
    channel_id: str | None = None
    live_status: str | None = None
    availability: str | None = None
    #: None when the video should be backed up; otherwise why it is skipped.
    skip_reason: str | None = None
    found_via: list[Source] = field(default_factory=list)

    @property
    def queued(self) -> bool:
        return self.skip_reason is None

    @property
    def status_text(self) -> str:
        """``queued`` or ``skipped: <reason>`` as shown in the preview and report."""
        return "queued" if self.queued else f"skipped: {self.skip_reason}"

    def merge(self, other: FoundVideo) -> None:
        """Fold in the same video found elsewhere: keep known values, add sources (F4a)."""
        for name in ("title", "duration_s", "upload_date", "channel", "channel_id", "live_status", "availability"):
            if getattr(self, name) is None and getattr(other, name) is not None:
                setattr(self, name, getattr(other, name))
        if self.skip_reason is None:
            self.skip_reason = other.skip_reason
        for source in other.found_via:
            if source not in self.found_via:
                self.found_via.append(source)


@dataclass(frozen=True)
class DiscoveryError:
    """A link, or part of one, that could not be read."""

    link: Link
    reason: str

    def __str__(self) -> str:
        return f"{self.link.url}: {self.reason}"


@dataclass
class DiscoveryResult:
    """Every video found, in the order first seen, plus link-level errors."""

    videos: dict[str, FoundVideo] = field(default_factory=dict)
    errors: list[DiscoveryError] = field(default_factory=list)
    #: True when YouTube's bot check stopped discovery (NF11b); later links were not read.
    blocked: bool = False

    def add(self, video: FoundVideo) -> None:
        existing = self.videos.get(video.video_id)
        if existing is None:
            self.videos[video.video_id] = video
        else:
            existing.merge(video)

    @property
    def queued(self) -> list[FoundVideo]:
        return [v for v in self.videos.values() if v.queued]

    @property
    def skipped(self) -> list[FoundVideo]:
        return [v for v in self.videos.values() if not v.queued]


# ------------------------------------------------------------------- yt-dlp
class ListingFailed(Exception):
    """yt-dlp could not read a listing page; ``str(exc)`` is the reason.

    Attributes:
        code: ``missing_tab`` (the channel has no such tab), ``bot_check``,
            ``rate_limited`` or ``listing_error``.
    """

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code or classify_listing_error(message)


def classify_listing_error(message: str) -> str:
    """Sort a yt-dlp error message into a ListingFailed code."""
    text = message.lower()
    if "does not have a" in text and "tab" in text:
        return "missing_tab"
    if "not a bot" in text:
        return "bot_check"
    if "http error 429" in text or "too many requests" in text or "rate-limit" in text or "rate limit" in text:
        return "rate_limited"
    return "listing_error"


#: Reads one listing URL and returns yt-dlp's info dict (entries included).
ExtractFn = Callable[[str], "dict[str, Any] | None"]


def build_listing_options() -> dict[str, Any]:
    """yt-dlp options for reading channel and playlist listings without downloading."""
    return {
        "extract_flat": "in_playlist",
        "skip_download": True,
        "lazy_playlist": False,
        "ignoreerrors": False,
        "extractor_retries": 3,
        "retries": 10,
        "noprogress": True,
        "quiet": True,
        "no_warnings": False,
        "logger": _YtdlpLogger(),
    }


def _ytdlp_extract(url: str) -> dict[str, Any] | None:
    """Default ExtractFn: flat-extract *url* with yt-dlp.

    Raises:
        ListingFailed: on any yt-dlp error.
    """
    import yt_dlp  # local import keeps --versions usable without yt-dlp
    from yt_dlp.utils import DownloadError

    ensure_tools_on_path()
    try:
        with yt_dlp.YoutubeDL(build_listing_options()) as ydl:
            info = ydl.extract_info(url, download=False)
            return ydl.sanitize_info(info) if info else None
    except DownloadError as exc:
        raise ListingFailed(str(exc).replace("ERROR: ", "", 1)) from exc
    except OSError as exc:
        raise ListingFailed(f"network or file system error: {exc}") from exc


# ----------------------------------------------------------------- entries
def skip_reason_for(entry: dict[str, Any]) -> str | None:
    """Why a listed video can't be backed up, or None if it can (F1b, F1c)."""
    if entry.get("live_status") in _NOT_YET_LIVE_STATUSES:
        return SKIP_NOT_YET_AVAILABLE
    availability = entry.get("availability")
    if availability in _SIGN_IN_AVAILABILITY:
        return SKIP_REQUIRES_SIGN_IN
    if availability == "private" or str(entry.get("title") or "").strip().lower() in _UNAVAILABLE_TITLES:
        return SKIP_UNAVAILABLE
    return None


def _upload_date(entry: dict[str, Any]) -> str | None:
    if entry.get("upload_date"):
        return str(entry["upload_date"])
    stamp = entry.get("timestamp") or entry.get("release_timestamp")
    if isinstance(stamp, (int, float)):
        return datetime.fromtimestamp(stamp, tz=timezone.utc).strftime("%Y%m%d")
    return None


def video_from_entry(entry: dict[str, Any], source: Source, listing: dict[str, Any]) -> FoundVideo | None:
    """Turn one flat listing entry into a FoundVideo, or None if it isn't a video."""
    video_id = entry.get("id")
    ie_key = entry.get("ie_key")
    if not isinstance(video_id, str) or not is_video_id(video_id) or (ie_key and ie_key != "Youtube"):
        log.debug("%s: ignoring non-video entry %r (%s)", source, video_id, ie_key)
        return None
    duration = entry.get("duration")
    return FoundVideo(
        video_id=video_id,
        url=canonical_video_url(video_id),
        title=entry.get("title") or None,
        duration_s=float(duration) if isinstance(duration, (int, float)) else None,
        upload_date=_upload_date(entry),
        # Channel tabs often leave these out of each entry; the tab itself has them.
        channel=entry.get("channel") or entry.get("uploader")
        or (listing.get("channel") if source.kind is SourceKind.CHANNEL else None),
        channel_id=entry.get("channel_id")
        or (listing.get("channel_id") if source.kind is SourceKind.CHANNEL else None),
        live_status=entry.get("live_status"),
        availability=entry.get("availability"),
        skip_reason=skip_reason_for(entry),
        found_via=[source],
    )


def _add_listing(result: DiscoveryResult, listing: dict[str, Any] | None, source: Source) -> int:
    """Add every video in a listing; return how many were found."""
    count = 0
    for entry in (listing or {}).get("entries") or []:
        if not isinstance(entry, dict):
            continue
        video = video_from_entry(entry, source, listing or {})
        if video:
            result.add(video)
            count += 1
    return count


# ------------------------------------------------------------------ discover
class _Blocked(Exception):
    """Internal: YouTube's bot check; stop reading links."""


def _record_failure(result: DiscoveryResult, link: Link, prefix: str, exc: ListingFailed) -> None:
    result.errors.append(DiscoveryError(link, f"{prefix}{exc}"))
    if exc.code == "bot_check":
        result.blocked = True
        raise _Blocked from exc


def _discover_channel(link: Link, extract: ExtractFn, result: DiscoveryResult) -> None:
    for tab, label in CHANNEL_TABS.items():
        try:
            listing = extract(f"{link.url}/{tab}")
        except ListingFailed as exc:
            if exc.code == "missing_tab":
                log.info("%s: no %s tab", link.key, label)
                continue
            _record_failure(result, link, f"{label} tab: ", exc)
            if tab == "videos":
                return  # the channel itself can't be read; the other tabs would fail the same way
            continue
        title = (listing or {}).get("channel") or (listing or {}).get("uploader") or ""
        source = Source(SourceKind.CHANNEL, link.key, tab=tab, title=title)
        count = _add_listing(result, listing, source)
        log.info("%s: %d in the %s tab", source.title or link.key, count, label)


def _discover_playlist(link: Link, extract: ExtractFn, result: DiscoveryResult) -> None:
    try:
        listing = extract(link.url)
    except ListingFailed as exc:
        _record_failure(result, link, "", exc)
        return
    source = Source(SourceKind.PLAYLIST, link.key, title=(listing or {}).get("title") or "")
    count = _add_listing(result, listing, source)
    log.info("%s: %d videos", source, count)


def discover(links: Iterable[Link], extract_fn: ExtractFn | None = None) -> DiscoveryResult:
    """Find every video behind *links*, each video once (F1-F3, F4a).

    Args:
        links: classified links (from ``classify_url`` or a list file).
        extract_fn: reads one listing URL; defaults to yt-dlp. Tests pass a fake.

    Returns:
        The videos in the order first seen, link-level errors, and whether
        YouTube's bot check stopped discovery early.
    """
    extract = extract_fn or _ytdlp_extract
    result = DiscoveryResult()
    seen: set[Link] = set()
    for link in links:
        if link in seen:
            continue
        seen.add(link)
        try:
            if link.kind is LinkKind.VIDEO:
                result.add(FoundVideo(link.key, link.url, found_via=[Source(SourceKind.LINK, link.key)]))
            elif link.kind is LinkKind.PLAYLIST:
                _discover_playlist(link, extract, result)
            elif link.kind is LinkKind.CHANNEL:
                _discover_channel(link, extract, result)
        except _Blocked:
            log.error("YouTube asked to confirm this is not a bot; stopped reading links")
            break
    log.info("Found %d videos: %d to back up, %d skipped, %d link errors",
             len(result.videos), len(result.queued), len(result.skipped), len(result.errors))
    return result
