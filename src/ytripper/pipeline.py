"""Per-video pipeline: skip-if-done -> download -> verify -> record (Increment 1).

Status flow: queued -> downloading -> downloaded -> verified | failed.
The manifest is saved after every transition so an interruption at any
point leaves a consistent, resumable state.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Callable

from . import downloader, verifier
from .logging_setup import get_logger
from .manifest import Manifest, Status
from .report import write_report
from .urls import canonical_video_url, parse_video_id
from .verifier import Expected, VerifyResult

log = get_logger("pipeline")

DownloadFn = Callable[[str, Path, Path], downloader.DownloadResult]
VerifyFn = Callable[[Path, Expected, str], VerifyResult]


class Outcome(str, Enum):
    SKIPPED = "skipped"
    VERIFIED = "verified"
    FAILED = "failed"
    INVALID = "invalid"


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return Path(os.path.relpath(path, root)).as_posix()


def backup_video(
    url: str,
    output_dir: Path,
    tools_dir: Path,
    ffprobe: str = "ffprobe",
    *,
    manifest: Manifest | None = None,
    download_fn: DownloadFn = downloader.download,
    verify_fn: VerifyFn = verifier.verify_file,
) -> Outcome:
    """Back up a single video URL, updating the manifest and report."""
    video_id = parse_video_id(url)
    if not video_id:
        log.error("Not a valid YouTube video URL: %s", url)
        return Outcome.INVALID

    manifest = manifest or Manifest.load(output_dir)
    canonical = canonical_video_url(video_id)

    if manifest.is_complete(video_id):
        log.info("%s already verified - skipping (0 bytes downloaded)", video_id)
        write_report(manifest)
        return Outcome.SKIPPED

    manifest.set_status(video_id, Status.DOWNLOADING, source_url=canonical)
    manifest.save()
    log.info("Downloading %s", canonical)

    try:
        result = download_fn(canonical, output_dir, tools_dir)
    except downloader.DownloadFailed as exc:
        log.error("%s download failed: %s", video_id, exc)
        manifest.fail(video_id, "download", str(exc), exc.code)
        manifest.save()
        write_report(manifest)
        return Outcome.FAILED

    info = result.info
    exp = result.expected
    manifest.set_status(
        video_id,
        Status.DOWNLOADED,
        title=info.get("title"),
        channel=info.get("channel") or info.get("uploader"),
        channel_id=info.get("channel_id"),
        upload_date=info.get("upload_date"),
        best_available={"height": exp.height, "fps": exp.fps, "vcodec": exp.vcodec,
                        "acodec": exp.acodec, "format_id": info.get("format_id")},
    )
    manifest.save()

    check = verify_fn(result.filepath, exp, ffprobe)
    saved = dict(check.saved, path=_relative(result.filepath, output_dir))
    if check.ok:
        manifest.set_status(video_id, Status.VERIFIED, saved=saved)
        log.info("%s verified: %sp %sfps %s+%s -> %s", video_id, saved.get("height"), saved.get("fps"),
                 saved.get("vcodec"), saved.get("acodec"), saved["path"])
        outcome = Outcome.VERIFIED
    else:
        manifest.ensure(video_id, saved=saved)
        manifest.fail(video_id, "verify", "; ".join(check.reasons), "verification_failed")
        log.error("%s failed verification: %s", video_id, "; ".join(check.reasons))
        outcome = Outcome.FAILED
    manifest.save()
    write_report(manifest)
    return outcome
