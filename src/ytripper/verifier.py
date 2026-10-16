"""Post-download verification with ffprobe (F7, NF1, F5).

A file passes only if it has a video and an audio stream, its duration is
within tolerance of YouTube's, its resolution/frame rate match the best
available format, and its codecs are the ones that were downloaded (i.e.
nothing was re-encoded).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

DURATION_TOLERANCE_S = 2.0
FPS_TOLERANCE = 0.5
_FFPROBE_TIMEOUT_S = 120

#: yt-dlp codec string prefix -> ffprobe codec_name
_CODEC_PREFIXES: tuple[tuple[str, str], ...] = (
    ("avc1", "h264"), ("avc3", "h264"), ("h264", "h264"),
    ("vp09", "vp9"), ("vp9", "vp9"), ("vp8", "vp8"),
    ("av01", "av1"), ("av1", "av1"),
    ("hev1", "hevc"), ("hvc1", "hevc"), ("hevc", "hevc"),
    ("mp4a", "aac"), ("aac", "aac"),
    ("opus", "opus"), ("vorbis", "vorbis"),
    ("ec-3", "eac3"), ("eac3", "eac3"), ("ac-3", "ac3"), ("ac3", "ac3"),
    ("flac", "flac"), ("mp3", "mp3"),
)


@dataclass(frozen=True)
class Expected:
    """What the saved file must match."""

    height: int | None
    fps: float | None
    vcodec: str | None
    acodec: str | None
    duration_s: float | None


@dataclass
class VerifyResult:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    saved: dict[str, Any] = field(default_factory=dict)


def normalize_codec(codec: str | None) -> str | None:
    """Map a yt-dlp or ffprobe codec string to a comparable ffprobe name."""
    if not codec or codec == "none":
        return None
    lowered = codec.lower()
    for prefix, name in _CODEC_PREFIXES:
        if lowered.startswith(prefix):
            return name
    return lowered.split(".")[0]


def parse_rate(rate: str | None) -> float | None:
    """Parse an ffprobe rational like ``30000/1001`` into frames per second."""
    if not rate or rate in ("0/0", "N/A"):
        return None
    try:
        value = float(Fraction(rate))
    except (ValueError, ZeroDivisionError):
        return None
    return round(value, 3) if value > 0 else None


def run_ffprobe(path: Path, ffprobe: str = "ffprobe") -> dict[str, Any]:
    """Return ffprobe's JSON description of *path* (streams + format)."""
    result = subprocess.run(  # noqa: S603 - fixed argument list, no shell
        [ffprobe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_FFPROBE_TIMEOUT_S,
        check=False,
        shell=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe exited {result.returncode}: {result.stderr.strip()[:500]}")
    return json.loads(result.stdout or "{}")


def evaluate(probe: dict[str, Any], expected: Expected, size_bytes: int | None = None) -> VerifyResult:
    """Compare ffprobe output against expectations (pure function)."""
    streams = probe.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not (s.get("disposition") or {}).get("attached_pic")), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = probe.get("format") or {}

    duration: float | None
    try:
        duration = float(fmt.get("duration")) if fmt.get("duration") not in (None, "N/A") else None
    except (TypeError, ValueError):
        duration = None

    saved = {
        "height": video.get("height") if video else None,
        "width": video.get("width") if video else None,
        "fps": parse_rate(video.get("avg_frame_rate") or video.get("r_frame_rate")) if video else None,
        "vcodec": video.get("codec_name") if video else None,
        "acodec": audio.get("codec_name") if audio else None,
        "duration_s": round(duration, 3) if duration is not None else None,
        "size_bytes": size_bytes,
    }

    reasons: list[str] = []
    if video is None:
        reasons.append("no video stream")
    if audio is None:
        reasons.append("no audio stream")
    if expected.duration_s is not None:
        if duration is None:
            reasons.append("duration unknown")
        elif abs(duration - expected.duration_s) > DURATION_TOLERANCE_S:
            reasons.append(f"duration {duration:.1f}s differs from YouTube's {expected.duration_s:.1f}s")
    if video is not None and expected.height is not None and saved["height"] != expected.height:
        reasons.append(f"height {saved['height']} != best available {expected.height}")
    if video is not None and expected.fps is not None:
        if saved["fps"] is None or abs(saved["fps"] - expected.fps) > FPS_TOLERANCE:
            reasons.append(f"fps {saved['fps']} != best available {expected.fps}")
    exp_v, exp_a = normalize_codec(expected.vcodec), normalize_codec(expected.acodec)
    if video is not None and exp_v and normalize_codec(saved["vcodec"]) != exp_v:
        reasons.append(f"video codec {saved['vcodec']} != downloaded {exp_v} (re-encoded?)")
    if audio is not None and exp_a and normalize_codec(saved["acodec"]) != exp_a:
        reasons.append(f"audio codec {saved['acodec']} != downloaded {exp_a} (re-encoded?)")

    return VerifyResult(ok=not reasons, reasons=reasons, saved=saved)


def verify_file(path: Path, expected: Expected, ffprobe: str = "ffprobe") -> VerifyResult:
    """Probe *path* and evaluate it; never raises for ordinary failures."""
    if not path.is_file():
        return VerifyResult(False, [f"file not found: {path}"])
    try:
        probe = run_ffprobe(path, ffprobe)
    except (OSError, subprocess.TimeoutExpired, RuntimeError, json.JSONDecodeError) as exc:
        return VerifyResult(False, [f"ffprobe failed: {exc}"])
    return evaluate(probe, expected, size_bytes=path.stat().st_size)
