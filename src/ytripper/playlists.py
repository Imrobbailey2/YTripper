"""Discover and run playlist backups using the single-video pipeline."""

from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from . import downloader
from .logging_setup import get_logger
from .manifest import Manifest, Status
from .pipeline import Outcome, _write_json, backup_video
from .report import write_report
from .urls import canonical_video_url, is_video_id

log = get_logger("playlists")
_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
_PLAYLIST_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class DiscoveryError(Exception):
    """Playlist discovery failed or returned incomplete data."""


@dataclass
class Video:
    """One unique video and its playlist memberships."""

    video_id: str
    title: str
    duration: float | None = None
    upload_date: str | None = None
    memberships: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Discovery:
    """The unique videos and entries that could not be queued."""

    videos: dict[str, Video] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    playlist_count: int = 0


def _validated_url(url: str, page: bool) -> str:
    try:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower()
    except ValueError as exc:
        raise DiscoveryError(f"Invalid YouTube URL: {url}") from exc
    if parsed.scheme not in ("http", "https") or host not in _HOSTS:
        raise DiscoveryError(f"Expected a YouTube URL: {url}")
    if page:
        parts = [part for part in parsed.path.split("/") if part]
        valid = (len(parts) == 2 and parts[0].startswith("@") and len(parts[0]) > 1
                 and parts[1] == "playlists")
        valid |= (len(parts) == 3 and parts[0] in ("channel", "user", "c")
                  and bool(parts[1]) and parts[2] == "playlists")
        if not valid:
            raise DiscoveryError("Expected a YouTube channel playlists page URL")
        return f"https://www.youtube.com/{'/'.join(parts)}"
    playlist_id = (parse_qs(parsed.query).get("list") or [""])[0]
    if parsed.path not in ("/playlist", "/watch") or not _PLAYLIST_ID.fullmatch(playlist_id):
        raise DiscoveryError("Expected a YouTube playlist URL with a valid list ID")
    return f"https://www.youtube.com/playlist?list={playlist_id}"


def discover(url: str, *, page: bool, include_other_channels: bool, tools_dir: Path) -> Discovery:
    """Enumerate playlist entries without downloading media."""
    import yt_dlp
    from yt_dlp.utils import DownloadError

    url = _validated_url(url, page)
    downloader.ensure_tools_on_path(tools_dir)
    options = {
        "extract_flat": True, "skip_download": True, "quiet": True,
        "ignoreerrors": False, "logger": downloader._YtdlpLogger(),
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            root = ydl.extract_info(url, download=False)
            if not isinstance(root, dict) or root.get("entries") is None:
                raise DiscoveryError("YouTube did not return a playlist listing")
            result = Discovery()
            channel_id = (root.get("channel_id") or root.get("id")) if page else None
            if page and not include_other_channels and not channel_id:
                raise DiscoveryError("Cannot determine the channel ID for uploader filtering")
            if page:
                playlists = list(root["entries"])
                for item in playlists:
                    if not isinstance(item, dict) or not _PLAYLIST_ID.fullmatch(str(item.get("id") or "")):
                        raise DiscoveryError("Channel playlist listing contains an invalid entry")
                    playlist_url = f'https://www.youtube.com/playlist?list={item["id"]}'
                    data = ydl.extract_info(playlist_url, download=False)
                    _collect(result, data, channel_id if not include_other_channels else None)
            else:
                _collect(result, root, None)
            return result
    except DownloadError as exc:
        raise DiscoveryError(f"Could not discover playlists: {exc}") from exc


def _collect(result: Discovery, playlist: Any, channel_id: str | None) -> None:
    if not isinstance(playlist, dict) or playlist.get("entries") is None:
        raise DiscoveryError("YouTube returned an incomplete playlist")
    playlist_id = str(playlist.get("id") or "")
    title = str(playlist.get("title") or playlist_id)
    if not _PLAYLIST_ID.fullmatch(playlist_id):
        raise DiscoveryError(f"Playlist {title!r} has no valid ID")
    result.playlist_count += 1
    for position, item in enumerate(playlist["entries"], 1):
        if not isinstance(item, dict) or not is_video_id(str(item.get("id") or "")):
            result.skipped.append(f"{title} #{position}: unavailable or invalid entry")
            continue
        vid = item["id"]
        name = str(item.get("title") or vid)
        if item.get("availability") in ("private", "premium_only", "subscriber_only", "needs_auth"):
            result.skipped.append(f"{title} #{position}: {name} requires sign-in")
            continue
        if item.get("live_status") in ("is_live", "is_upcoming"):
            result.skipped.append(f"{title} #{position}: {name} not yet available")
            continue
        if channel_id and item.get("channel_id") != channel_id:
            reason = "other channel" if item.get("channel_id") else "uploader unknown"
            result.skipped.append(f"{title} #{position}: {name} skipped ({reason})")
            continue
        video = result.videos.setdefault(
            vid, Video(vid, name, item.get("duration"), item.get("upload_date"))
        )
        membership = {"id": playlist_id, "title": title, "position": position}
        if membership not in video.memberships:
            video.memberships.append(membership)


def preview(discovery: Discovery, manifest: Manifest) -> None:
    """Print the proposed queue without downloading media."""
    print(f"Playlists: {discovery.playlist_count}; unique videos: {len(discovery.videos)}")
    complete = sum(manifest.is_complete(v.video_id) for v in discovery.videos.values())
    print(f"Already verified: {complete}; to process: {len(discovery.videos) - complete}")
    print("Estimated size: unknown (not supplied by flat playlist discovery)")
    for video in discovery.videos.values():
        status = "already verified" if manifest.is_complete(video.video_id) else "to process"
        print(f"  {video.title} [{video.video_id}] | {video.duration if video.duration is not None else 'unknown'} s"
              f" | {video.upload_date or 'date unknown'} | {status}")
    for message in discovery.skipped:
        print(f"  Skipped: {message}")


def record_discovery(discovery: Discovery, manifest: Manifest, *, planned: bool) -> None:
    """Persist memberships, including for previously verified videos."""
    for video in discovery.videos.values():
        existing = manifest.get(video.video_id)
        memberships = list((existing or {}).get("playlists") or [])
        for membership in video.memberships:
            # A position is part of the membership: a playlist may repeat a video.
            memberships = [p for p in memberships if
                           (p.get("id"), p.get("position")) != (membership["id"], membership["position"])]
            memberships.append(membership)
        entry = manifest.ensure(video.video_id, playlists=memberships)
        if existing is None:
            entry["title"] = video.title
            if planned:
                entry["status"] = Status.PLANNED.value
        elif not planned and entry.get("status") == Status.PLANNED.value:
            entry["status"] = Status.QUEUED.value
        details_path = entry.get("details_path")
        if manifest.is_complete(video.video_id) and not details_path:
            raise DiscoveryError(f"Cannot update playlist details for {video.video_id}: details path is missing")
        if details_path and manifest.is_complete(video.video_id):
            path = manifest.output_dir / details_path
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(record, dict):
                    raise ValueError("details document is not an object")
                record["playlists"] = memberships
                _write_json(path, record)
            except (OSError, ValueError) as exc:
                raise DiscoveryError(f"Cannot update playlist details for {video.video_id}: {exc}") from exc
    manifest.save()
    write_report(manifest)


def run_queue(
    discovery: Discovery, manifest: Manifest, tools_dir: Path, ffprobe: str,
    *, sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Process each unique video, retrying failures once; return overall success."""
    pending = list(discovery.videos)
    failures: list[str] = []
    counts = {Outcome.VERIFIED: 0, Outcome.SKIPPED: 0}
    attempted = False
    for pass_number in (1, 2):
        retry: list[str] = []
        for video_id in pending:
            previous_error = (manifest.get(video_id) or {}).get("last_error") or {}
            if previous_error.get("code") == "quarantine_failed":
                failures.append(f"{video_id}: unresolved quarantine failure: {previous_error.get('message')}")
                continue
            if attempted and not manifest.is_complete(video_id):
                pause = random.uniform(5, 15)
                log.info("Pausing %.1f seconds between videos", pause)
                sleep(pause)
            rate_retries = 0
            while True:
                outcome = backup_video(canonical_video_url(video_id), manifest.output_dir, tools_dir,
                                       ffprobe, manifest=manifest)
                attempted = True
                error = (manifest.get(video_id) or {}).get("last_error") or {}
                message = str(error.get("message") or outcome.value)
                if outcome in counts or not ("429" in message or "rate limit" in message.lower()):
                    break
                if rate_retries == 3:
                    break
                rate_retries += 1
                log.warning("Rate limit for %s; waiting 10 minutes before retry %d of 3",
                            video_id, rate_retries)
                sleep(600)
            if outcome in counts:
                counts[outcome] += 1
                continue
            if "confirm you" in message.lower() and "bot" in message.lower():
                log.error("YouTube requested bot confirmation; stopping. Remaining videos stay queued.")
                return False
            if error.get("code") == "quarantine_failed":
                log.error("Cannot safely retry %s: %s", video_id, message)
                failures.append(f"{video_id}: {message}")
                continue
            if "429" in message or "rate limit" in message.lower():
                failures.append(f"{video_id}: {message}")
                continue
            if pass_number == 1:
                retry.append(video_id)
            else:
                failures.append(f"{video_id}: {message}")
        pending = retry
        if not pending:
            break
        log.info("Retrying %d failed videos once", len(pending))
    log.info("Playlist run: %d verified, %d already verified, %d failed, %d discovery entries skipped",
             counts[Outcome.VERIFIED], counts[Outcome.SKIPPED], len(failures), len(discovery.skipped))
    for failure in failures:
        log.error("%s", failure)
    return not failures and not discovery.skipped
