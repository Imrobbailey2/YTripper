"""Tests for ffprobe-based verification (pure evaluation + real ffmpeg clips)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from ytripper import verifier
from ytripper.paths import TOOLS_DIR
from ytripper.verifier import Expected, evaluate, normalize_codec, parse_rate


def _probe(height=2160, rate="60/1", vcodec="vp9", acodec="opus", duration="120.0", audio=True, video=True):
    streams = []
    if video:
        streams.append({"codec_type": "video", "codec_name": vcodec, "height": height, "width": 3840,
                        "avg_frame_rate": rate, "r_frame_rate": rate})
    if audio:
        streams.append({"codec_type": "audio", "codec_name": acodec})
    return {"streams": streams, "format": {"duration": duration}}


EXPECTED = Expected(height=2160, fps=60.0, vcodec="vp09.00.51.08", acodec="opus", duration_s=120.0)


@pytest.mark.parametrize(
    ("codec", "expected"),
    [("avc1.640028", "h264"), ("vp09.00.51.08", "vp9"), ("av01.0.08M.08", "av1"),
     ("mp4a.40.2", "aac"), ("opus", "opus"), ("none", None), (None, None), ("h264", "h264")],
)
def test_normalize_codec(codec, expected) -> None:
    assert normalize_codec(codec) == expected


@pytest.mark.parametrize(("rate", "fps"), [("30000/1001", 29.97), ("60/1", 60.0), ("0/0", None), ("N/A", None), (None, None)])
def test_parse_rate(rate, fps) -> None:
    assert parse_rate(rate) == fps


def test_matching_file_passes() -> None:
    result = evaluate(_probe(), EXPECTED, size_bytes=123)
    assert result.ok, result.reasons
    assert result.saved["height"] == 2160 and result.saved["size_bytes"] == 123


@pytest.mark.parametrize(
    ("probe_kwargs", "fragment"),
    [
        ({"audio": False}, "no audio stream"),
        ({"video": False}, "no video stream"),
        ({"height": 1080}, "height 1080"),
        ({"rate": "30/1"}, "fps 30.0"),
        ({"vcodec": "h264"}, "video codec"),
        ({"acodec": "aac"}, "audio codec"),
        ({"duration": "100.0"}, "duration 100.0s"),
        ({"duration": "N/A"}, "duration unknown"),
    ],
)
def test_mismatches_fail(probe_kwargs, fragment) -> None:
    result = evaluate(_probe(**probe_kwargs), EXPECTED)
    assert not result.ok
    assert any(fragment in r for r in result.reasons), result.reasons


def test_duration_within_tolerance_passes() -> None:
    assert evaluate(_probe(duration="121.5"), EXPECTED).ok


def test_attached_picture_is_not_the_video_stream() -> None:
    probe = _probe()
    probe["streams"].insert(0, {"codec_type": "video", "codec_name": "mjpeg", "height": 720,
                                "disposition": {"attached_pic": 1}})
    assert evaluate(probe, EXPECTED).ok


def test_verify_file_missing(tmp_path: Path) -> None:
    result = verifier.verify_file(tmp_path / "nope.mkv", EXPECTED)
    assert not result.ok and "file not found" in result.reasons[0]


def test_verify_file_ffprobe_error_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "x.mkv"
    f.write_bytes(b"x")

    def boom(*_a, **_k):
        raise OSError("ffprobe missing")

    monkeypatch.setattr(verifier.subprocess, "run", boom)
    result = verifier.verify_file(f, EXPECTED)
    assert not result.ok and "ffprobe failed" in result.reasons[0]


# --------------------------------------------------------------- real clips
def _find(name: str) -> str | None:
    for candidate in (TOOLS_DIR / f"{name}.exe", TOOLS_DIR / name):
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


FFMPEG, FFPROBE = _find("ffmpeg"), _find("ffprobe")
needs_ffmpeg = pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="ffmpeg/ffprobe not available")


def _make_clip(path: Path, *, audio: bool = True, size: str = "1280x720", rate: int = 30, seconds: int = 3) -> None:
    args = [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}:duration={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "libopus"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(args, check=True, capture_output=True, timeout=120)


@needs_ffmpeg
def test_real_clip_passes(tmp_path: Path) -> None:
    clip = tmp_path / "ok.mkv"
    _make_clip(clip)
    exp = Expected(height=720, fps=30.0, vcodec="avc1.64001f", acodec="opus", duration_s=3.0)
    result = verifier.verify_file(clip, exp, FFPROBE)
    assert result.ok, result.reasons


@needs_ffmpeg
def test_real_clip_without_audio_fails(tmp_path: Path) -> None:
    clip = tmp_path / "noaudio.mkv"
    _make_clip(clip, audio=False)
    exp = Expected(height=720, fps=30.0, vcodec="avc1", acodec="opus", duration_s=3.0)
    result = verifier.verify_file(clip, exp, FFPROBE)
    assert not result.ok and "no audio stream" in result.reasons


@needs_ffmpeg
def test_real_clip_lower_resolution_fails(tmp_path: Path) -> None:
    clip = tmp_path / "low.mkv"
    _make_clip(clip, size="640x360")
    exp = Expected(height=720, fps=30.0, vcodec="avc1", acodec="opus", duration_s=3.0)
    result = verifier.verify_file(clip, exp, FFPROBE)
    assert not result.ok and any("height 360" in r for r in result.reasons)
