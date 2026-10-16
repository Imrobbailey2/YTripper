"""Tests for yt-dlp option building, expectations and the per-video pipeline.

yt-dlp itself is replaced by fakes so these tests never touch the network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ytripper import downloader
from ytripper.downloader import DownloadFailed, DownloadResult, best_available, build_options, expected_from_info
from ytripper.manifest import Manifest, Status
from ytripper.pipeline import Outcome, backup_video
from ytripper.verifier import Expected, VerifyResult

VID = "_hqB_JFI3e8"
URL = f"https://youtu.be/{VID}?si=tracking"

INFO = {
    "id": VID,
    "title": "Sample: talk / part 1?",
    "channel": "UF Doctor of Plant Medicine",
    "channel_id": "UCxxxx",
    "upload_date": "20240501",
    "duration": 600,
    "format_id": "313+251",
    "formats": [
        {"format_id": "sb0", "vcodec": "none", "acodec": "none", "ext": "mhtml"},
        {"format_id": "137", "vcodec": "avc1.640028", "height": 1080, "fps": 30},
        {"format_id": "299", "vcodec": "avc1.64002a", "height": 1080, "fps": 60},
        {"format_id": "313", "vcodec": "vp09.00.51.08", "height": 2160, "fps": 30},
        {"format_id": "999", "vcodec": "vp09", "height": 4320, "fps": 30, "has_drm": True},
        {"format_id": "251", "vcodec": "none", "acodec": "opus"},
    ],
    "requested_formats": [
        {"format_id": "313", "vcodec": "vp09.00.51.08", "acodec": "none"},
        {"format_id": "251", "vcodec": "none", "acodec": "opus"},
    ],
}


def test_build_options_core_settings(tmp_path: Path) -> None:
    opts = build_options(tmp_path, tools_dir=tmp_path)
    assert opts["format"] == "bv*+ba/b"
    assert opts["merge_output_format"] == "mkv"
    assert opts["windowsfilenames"] is True
    assert opts["noplaylist"] is True
    assert opts["paths"]["temp"].endswith(".tmp")
    assert "%(id)s" in opts["outtmpl"]["default"]
    assert opts["outtmpl"]["default"].startswith("%(channel,uploader|Unknown channel)s/")
    # NF4: never any authentication material
    for forbidden in ("cookiefile", "cookiesfrombrowser", "username", "password", "usenetrc"):
        assert forbidden not in opts


def test_build_options_uses_project_ffmpeg_when_present(tmp_path: Path) -> None:
    (tmp_path / "ffmpeg.exe").write_bytes(b"")
    assert build_options(tmp_path, tools_dir=tmp_path)["ffmpeg_location"] == str(tmp_path)


def test_best_available_ignores_drm_and_storyboards() -> None:
    assert best_available(INFO) == (2160, 30.0)


def test_best_available_prefers_highest_fps_at_top_height() -> None:
    info = {"formats": [{"vcodec": "vp9", "height": 1080, "fps": 30}, {"vcodec": "vp9", "height": 1080, "fps": 60}]}
    assert best_available(info) == (1080, 60.0)


def test_expected_from_info() -> None:
    exp = expected_from_info(INFO)
    assert exp == Expected(height=2160, fps=30.0, vcodec="vp09.00.51.08", acodec="opus", duration_s=600.0)


def test_output_path_from_info() -> None:
    assert downloader.output_path_from_info({"requested_downloads": [{"filepath": "C:/x/y.mkv"}]}) == Path("C:/x/y.mkv")
    with pytest.raises(DownloadFailed):
        downloader.output_path_from_info({})


# ------------------------------------------------------------------ pipeline
class FakeDownloader:
    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def __call__(self, url: str, output_dir: Path, tools_dir: Path) -> DownloadResult:
        self.calls += 1
        assert url == f"https://www.youtube.com/watch?v={VID}"
        if self.fail:
            raise DownloadFailed("HTTP Error 403: Forbidden", code="http")
        target = output_dir / "UF Doctor of Plant Medicine" / f"2024-05-01 - Sample [{VID}]" / f"Sample [{VID}].mkv"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\x1aE\xdf\xa3fake-mkv")
        return DownloadResult(info=INFO, filepath=target, expected=expected_from_info(INFO))


def ok_verifier(path: Path, expected: Expected, ffprobe: str) -> VerifyResult:
    return VerifyResult(True, [], {"height": expected.height, "fps": expected.fps, "vcodec": "vp9",
                                   "acodec": "opus", "duration_s": 600.0, "size_bytes": path.stat().st_size})


def bad_verifier(path: Path, expected: Expected, ffprobe: str) -> VerifyResult:
    return VerifyResult(False, ["no audio stream"], {"height": 2160})


def test_pipeline_verifies_then_skips_on_rerun(tmp_path: Path) -> None:
    fake = FakeDownloader()
    first = backup_video(URL, tmp_path, tmp_path, download_fn=fake, verify_fn=ok_verifier)
    assert first is Outcome.VERIFIED

    entry = Manifest.load(tmp_path).get(VID)
    assert entry["status"] == Status.VERIFIED.value
    assert entry["saved"]["path"] == f"UF Doctor of Plant Medicine/2024-05-01 - Sample [{VID}]/Sample [{VID}].mkv"
    assert entry["best_available"]["height"] == 2160
    assert entry["attempts"] == 1

    second = backup_video(URL, tmp_path, tmp_path, download_fn=fake, verify_fn=ok_verifier)
    assert second is Outcome.SKIPPED
    assert fake.calls == 1  # NF3 / F8: nothing re-downloaded
    assert (tmp_path / "report.csv").exists()


def test_pipeline_redownloads_if_verified_file_was_deleted(tmp_path: Path) -> None:
    fake = FakeDownloader()
    backup_video(URL, tmp_path, tmp_path, download_fn=fake, verify_fn=ok_verifier)
    rel = Manifest.load(tmp_path).get(VID)["saved"]["path"]
    (tmp_path / rel).unlink()
    assert backup_video(URL, tmp_path, tmp_path, download_fn=fake, verify_fn=ok_verifier) is Outcome.VERIFIED
    assert fake.calls == 2


def test_pipeline_records_download_failure(tmp_path: Path) -> None:
    outcome = backup_video(URL, tmp_path, tmp_path, download_fn=FakeDownloader(fail=True), verify_fn=ok_verifier)
    assert outcome is Outcome.FAILED
    entry = Manifest.load(tmp_path).get(VID)
    assert entry["status"] == "failed"
    assert entry["last_error"] == {"stage": "download", "code": "http", "message": "HTTP Error 403: Forbidden"}


def test_pipeline_records_verification_failure_and_retries(tmp_path: Path) -> None:
    fake = FakeDownloader()
    assert backup_video(URL, tmp_path, tmp_path, download_fn=fake, verify_fn=bad_verifier) is Outcome.FAILED
    entry = Manifest.load(tmp_path).get(VID)
    assert entry["last_error"]["stage"] == "verify"
    # failed videos are retried on the next run
    assert backup_video(URL, tmp_path, tmp_path, download_fn=fake, verify_fn=ok_verifier) is Outcome.VERIFIED
    assert Manifest.load(tmp_path).get(VID)["attempts"] == 2


def test_pipeline_rejects_invalid_url(tmp_path: Path) -> None:
    fake = FakeDownloader()
    assert backup_video("https://example.com/x", tmp_path, tmp_path, download_fn=fake, verify_fn=ok_verifier) is Outcome.INVALID
    assert fake.calls == 0
    assert not (tmp_path / "manifest.json").exists()


def test_manifest_is_valid_json_after_run(tmp_path: Path) -> None:
    backup_video(URL, tmp_path, tmp_path, download_fn=FakeDownloader(), verify_fn=ok_verifier)
    data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert data["schema"] == 1 and VID in data["videos"]
