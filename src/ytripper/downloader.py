"""yt-dlp download wrapper (F5, F9, F10, NF1, NF4, NF5).

yt-dlp is embedded as a library (architecture decision 1) so the full format
list is available to verify that the best format was saved. Selection is
``bv*+ba/b`` merged into MKV by ffmpeg with stream copy (no re-encode).
No cookies or credentials are ever passed (NF4).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import description
from .logging_setup import get_logger
from .paths import TOOLS_DIR
from .verifier import Expected

FORMAT_SELECTOR = "bv*+ba/b"
MERGE_FORMAT = "mkv"
TEMP_DIR_NAME = ".tmp"
#: <Output>/<channel>/<YYYY-MM-DD> - <title> [<id>]/
#: Titles are truncated to 80 bytes to keep Windows paths manageable (NF5).
VIDEO_DIR_TEMPLATE = (
    "%(channel,uploader|Unknown channel)s/"
    "%(upload_date>%Y-%m-%d|unknown-date)s - %(title).80B [%(id)s]/"
)
#: .../<title> [<id>].mkv
OUTPUT_TEMPLATE = VIDEO_DIR_TEMPLATE + "%(title).80B [%(id)s].%(ext)s"
#: Sidecars use the video ID: <id>.description, <id>.info.json, <id>.<lang>.vtt, <id>.jpg/.webp
SIDECAR_TEMPLATE = VIDEO_DIR_TEMPLATE + "%(id)s.%(ext)s"

log = get_logger("downloader")


class DownloadFailed(Exception):
    """Raised when yt-dlp cannot download or merge a video."""

    def __init__(self, message: str, code: str = "download_error") -> None:
        super().__init__(message)
        self.code = code


@dataclass
class DownloadResult:
    info: dict[str, Any]
    filepath: Path
    expected: Expected
    #: Parsed description fields (F19); None lets the pipeline parse them itself.
    details: dict[str, Any] | None = None
    #: Where embedded chapters came from: youtube | description | none.
    chapters_source: str = "none"


class _YtdlpLogger:
    """Routes yt-dlp output into the run log (chatty lines at DEBUG)."""

    def debug(self, msg: str) -> None:
        log.debug(msg)

    def info(self, msg: str) -> None:
        log.debug(msg)

    def warning(self, msg: str) -> None:
        log.warning(msg)

    def error(self, msg: str) -> None:
        log.error(msg)


def _progress_hook(status: dict[str, Any]) -> None:
    """Single-line console progress for the current stream."""
    state = status.get("status")
    if state == "downloading":
        done = status.get("downloaded_bytes") or 0
        total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
        pct = f"{done / total * 100:5.1f}%" if total else "  ?  "
        speed = status.get("speed") or 0
        eta = status.get("eta")
        line = f"\r    {pct} of {total / 1048576:8.1f} MiB  {speed / 1048576:6.2f} MiB/s  ETA {eta if eta is not None else '?'}s   "
        sys.stderr.write(line)
        sys.stderr.flush()
    elif state == "finished":
        sys.stderr.write("\n")
        sys.stderr.flush()


def ensure_tools_on_path(tools_dir: Path = TOOLS_DIR) -> None:
    """Prepend the project tools directory to PATH for this process (Deno discovery)."""
    tools = str(tools_dir)
    current = os.environ.get("PATH", "")
    if tools_dir.is_dir() and tools not in current.split(os.pathsep):
        os.environ["PATH"] = tools + os.pathsep + current


def build_options(
    output_dir: Path,
    tools_dir: Path = TOOLS_DIR,
    progress_hook: Callable[[dict[str, Any]], None] | None = _progress_hook,
) -> dict[str, Any]:
    """Return the yt-dlp option dict used for every download."""
    opts: dict[str, Any] = {
        "format": FORMAT_SELECTOR,
        "merge_output_format": MERGE_FORMAT,
        "paths": {"home": str(output_dir), "temp": str(output_dir / TEMP_DIR_NAME)},
        "outtmpl": {
            "default": OUTPUT_TEMPLATE,
            "thumbnail": SIDECAR_TEMPLATE,
            "description": SIDECAR_TEMPLATE,
            "infojson": SIDECAR_TEMPLATE,
            "subtitle": SIDECAR_TEMPLATE,
        },
        # Sidecar files (F6, F19a). Only uploaded captions: auto-generated are off (decision 5).
        "writedescription": True,
        "writeinfojson": True,
        "writethumbnail": True,
        "writesubtitles": True,
        "writeautomaticsub": False,
        "subtitleslangs": ["all", "-live_chat"],
        # Embed chapters + metadata (artist = author) by stream copy; never attach the info JSON.
        "postprocessors": [
            {"key": "FFmpegMetadata", "add_chapters": True, "add_metadata": True, "add_infojson": False},
        ],
        "windowsfilenames": True,
        "noplaylist": True,
        "continuedl": True,
        "retries": 10,
        "fragment_retries": 10,
        "file_access_retries": 3,
        "noprogress": True,
        "quiet": True,
        "no_warnings": False,
        "logger": _YtdlpLogger(),
        "progress_hooks": [progress_hook] if progress_hook else [],
    }
    if (tools_dir / "ffmpeg.exe").is_file() or (tools_dir / "ffmpeg").is_file():
        opts["ffmpeg_location"] = str(tools_dir)
    return opts


def best_available(info: dict[str, Any]) -> tuple[int | None, float | None]:
    """Highest video height offered, and the highest fps at that height."""
    videos = [
        f for f in info.get("formats") or []
        if f.get("vcodec") not in (None, "none") and f.get("height") and not f.get("has_drm")
    ]
    if not videos:
        return info.get("height"), info.get("fps")
    top = max(int(f["height"]) for f in videos)
    fps_values = [float(f["fps"]) for f in videos if int(f["height"]) == top and f.get("fps")]
    return top, (max(fps_values) if fps_values else None)


def expected_from_info(info: dict[str, Any]) -> Expected:
    """Build verification expectations from yt-dlp's post-download info."""
    requested = info.get("requested_formats") or [info]
    vcodec = next((f.get("vcodec") for f in requested if f.get("vcodec") not in (None, "none")), None)
    acodec = next((f.get("acodec") for f in requested if f.get("acodec") not in (None, "none")), None)
    height, fps = best_available(info)
    duration = info.get("duration")
    return Expected(
        height=height,
        fps=fps,
        vcodec=vcodec,
        acodec=acodec,
        duration_s=float(duration) if duration else None,
        chapters=len(info.get("chapters") or []),
        artist=info.get("artist") or None,
    )


def _make_details_pp(holder: dict[str, Any]) -> Any:
    """yt-dlp 'pre_process' post-processor that parses the description (F19)
    and prepares the info dict so FFmpegMetadata embeds chapters + author."""
    from yt_dlp.postprocessor.common import PostProcessor

    class DescriptionDetailsPP(PostProcessor):  # type: ignore[misc]
        def run(self, info: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
            details = description.parse_description(
                info.get("description") or "",
                title=info.get("title") or "",
                channel=info.get("channel") or info.get("uploader") or "",
            )
            youtube_count = len(info.get("chapters") or [])
            source = description.apply_to_info(info, details)
            if source == "youtube" and details["chapters"] and len(details["chapters"]) != youtube_count:
                log.warning("%s: YouTube has %d chapters but the description lists %d; embedding YouTube's",
                            info.get("id"), youtube_count, len(details["chapters"]))
            elif source == "description":
                log.info("%s: no YouTube chapters; embedding %d chapters from the description",
                         info.get("id"), len(info["chapters"]))
            holder["details"], holder["chapters_source"] = details, source
            return [], info

    return DescriptionDetailsPP()


def output_path_from_info(info: dict[str, Any]) -> Path:
    """Final merged file path as reported by yt-dlp."""
    for item in info.get("requested_downloads") or []:
        if item.get("filepath"):
            return Path(item["filepath"])
    if info.get("filepath"):
        return Path(info["filepath"])
    raise DownloadFailed("yt-dlp did not report an output file path", code="no_output_path")


def download(url: str, output_dir: Path, tools_dir: Path = TOOLS_DIR) -> DownloadResult:
    """Download one video at best quality into *output_dir*.

    Raises:
        DownloadFailed: on any yt-dlp download/merge error.
    """
    import yt_dlp  # local import keeps --versions usable without yt-dlp
    from yt_dlp.utils import DownloadError

    ensure_tools_on_path(tools_dir)
    output_dir = output_dir.resolve()
    opts = build_options(output_dir, tools_dir)
    log.debug("yt-dlp %s options: %s", yt_dlp.version.__version__, {k: v for k, v in opts.items() if k != "logger"})
    holder: dict[str, Any] = {}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.add_post_processor(_make_details_pp(holder), when="pre_process")
            info = ydl.extract_info(url, download=True)
            info = ydl.sanitize_info(info)
    except DownloadError as exc:
        raise DownloadFailed(str(exc).replace("ERROR: ", "", 1)) from exc
    except OSError as exc:
        raise DownloadFailed(f"file system error: {exc}", code="os_error") from exc
    if not info:
        raise DownloadFailed("yt-dlp returned no information", code="no_info")
    return DownloadResult(
        info=info,
        filepath=output_path_from_info(info),
        expected=expected_from_info(info),
        details=holder.get("details"),
        chapters_source=holder.get("chapters_source", "none"),
    )
