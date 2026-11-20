"""Playlist discovery, membership, preview and queue tests; no network access."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import yt_dlp

from ytripper import __main__ as cli
from ytripper import playlists, versions
from ytripper.manifest import Manifest, Status
from ytripper.pipeline import Outcome

A = "aaaaaaaaaaa"
B = "bbbbbbbbbbb"
P1 = "PL_one"
P2 = "PL_two"
PAGE = "https://www.youtube.com/@example/playlists"
PLAYLIST = f"https://www.youtube.com/playlist?list={P1}"


def fixture_data() -> dict[str, dict]:
    return {
        PAGE: {"id": "UCowner", "channel_id": "UCowner", "entries": [{"id": P1}, {"id": P2}]},
        PLAYLIST: {
            "id": P1, "title": "First", "entries": [
                {"id": A, "title": "First video", "duration": 12, "channel_id": "UCowner"},
                {"id": B, "title": "Other video", "channel_id": "UCother"},
                None,
            ],
        },
        f"https://www.youtube.com/playlist?list={P2}": {
            "id": P2, "title": "Second", "entries": [
                {"id": A, "title": "First video", "channel_id": "UCowner"},
            ],
        },
    }


def fake_ytdl(monkeypatch: pytest.MonkeyPatch, data: dict[str, dict]) -> None:
    class FakeYoutubeDL:
        def __init__(self, options: dict) -> None:
            assert options["extract_flat"] and options["skip_download"]
            assert not any(key in options for key in ("cookiefile", "cookiesfrombrowser", "username", "password"))

        def __enter__(self) -> "FakeYoutubeDL":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def extract_info(self, url: str, download: bool) -> dict:
            assert not download
            return data[url]

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)


def test_discover_page_deduplicates_and_includes_other_channels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ytdl(monkeypatch, fixture_data())
    found = playlists.discover(PAGE, page=True, include_other_channels=True, tools_dir=tmp_path)
    assert found.playlist_count == 2
    assert set(found.videos) == {A, B}
    assert found.videos[A].memberships == [
        {"id": P1, "title": "First", "position": 1},
        {"id": P2, "title": "Second", "position": 1},
    ]
    assert len(found.skipped) == 1


def test_discover_page_filters_other_or_unknown_channel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = fixture_data()
    data[PLAYLIST]["entries"].append({"id": "ccccccccccc", "title": "Unknown"})
    fake_ytdl(monkeypatch, data)
    found = playlists.discover(PAGE, page=True, include_other_channels=False, tools_dir=tmp_path)
    assert list(found.videos) == [A]
    assert any("other channel" in item for item in found.skipped)
    assert any("uploader unknown" in item for item in found.skipped)


def test_single_playlist_includes_other_channel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ytdl(monkeypatch, fixture_data())
    found = playlists.discover(PLAYLIST, page=False, include_other_channels=False, tools_dir=tmp_path)
    assert set(found.videos) == {A, B}


@pytest.mark.parametrize(("url", "page"), [
    ("https://evil.example/playlist?list=PLx", False),
    ("https://youtube.com/watch?v=aaaaaaaaaaa", False),
    ("https://youtube.com/@example/videos", True),
    ("https://youtube.com/playlist?list=invalid%20id", False),
])
def test_discovery_rejects_bad_urls(url: str, page: bool, tmp_path: Path) -> None:
    with pytest.raises(playlists.DiscoveryError):
        playlists.discover(url, page=page, include_other_channels=True, tools_dir=tmp_path)


def test_discovery_does_not_hide_playlist_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = fixture_data()
    data[PLAYLIST] = {"id": P1, "title": "First"}
    fake_ytdl(monkeypatch, data)
    with pytest.raises(playlists.DiscoveryError, match="incomplete"):
        playlists.discover(PAGE, page=True, include_other_channels=True, tools_dir=tmp_path)


def test_memberships_update_existing_details_and_report(tmp_path: Path) -> None:
    path = tmp_path / "existing.mkv"
    path.write_bytes(b"video")
    details_path = tmp_path / f"{A}.details.json"
    details_path.write_text('{"title": "Old", "playlists": []}', encoding="utf-8")
    manifest = Manifest.load(tmp_path)
    manifest.set_status(A, Status.VERIFIED, saved={"path": path.name}, details_path=details_path.name,
                        playlists=[{"id": P1, "title": "Old title", "position": 1}])
    found = playlists.Discovery(videos={A: playlists.Video(A, "Video", memberships=[
        {"id": P1, "title": "New title", "position": 1}, {"id": P2, "title": "Other", "position": 2},
    ])})
    playlists.record_discovery(found, manifest, planned=False)
    memberships = json.loads(details_path.read_text(encoding="utf-8"))["playlists"]
    assert memberships == manifest.get(A)["playlists"]
    assert len(memberships) == 2 and memberships[0]["title"] == "New title"
    with (tmp_path / "report.csv").open(encoding="utf-8-sig", newline="") as file:
        row = next(csv.DictReader(file))
    assert row["playlist_count"] == "2" and "Other [PL_two] #2" in row["playlists"]


def test_missing_existing_details_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "existing.mkv").write_bytes(b"video")
    manifest = Manifest.load(tmp_path)
    manifest.set_status(A, Status.VERIFIED, saved={"path": "existing.mkv"}, details_path="missing.json")
    found = playlists.Discovery(videos={A: playlists.Video(A, "Video")})
    with pytest.raises(playlists.DiscoveryError, match="Cannot update"):
        playlists.record_discovery(found, manifest, planned=False)


def test_cancel_records_new_entries_as_planned_without_overwriting_existing(tmp_path: Path) -> None:
    manifest = Manifest.load(tmp_path)
    manifest.fail(A, "download", "failed previously")
    found = playlists.Discovery(videos={A: playlists.Video(A, "Old"), B: playlists.Video(B, "New")})
    playlists.record_discovery(found, manifest, planned=True)
    saved = Manifest.load(tmp_path)
    assert saved.get(A)["status"] == "failed"
    assert saved.get(B)["status"] == "planned"
    playlists.record_discovery(found, saved, planned=False)
    assert Manifest.load(tmp_path).get(B)["status"] == "queued"


def test_queue_retries_failures_and_continues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = Manifest.load(tmp_path)
    found = playlists.Discovery(videos={A: playlists.Video(A, "A"), B: playlists.Video(B, "B")})
    playlists.record_discovery(found, manifest, planned=False)
    calls: list[str] = []
    waits: list[float] = []

    def fake_backup(url: str, output: Path, tools: Path, ffprobe: str, *, manifest: Manifest) -> Outcome:
        vid = url[-11:]
        calls.append(vid)
        if vid == A and calls.count(A) == 1:
            manifest.fail(A, "download", "HTTP 403")
            return Outcome.FAILED
        manifest.set_status(vid, Status.VERIFIED)
        return Outcome.VERIFIED

    monkeypatch.setattr(playlists, "backup_video", fake_backup)
    assert playlists.run_queue(found, manifest, tmp_path, "ffprobe", sleep=waits.append)
    assert calls == [A, B, A]
    assert len(waits) == 2 and all(5 <= wait <= 15 for wait in waits)


def test_bot_challenge_stops_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = Manifest.load(tmp_path)
    found = playlists.Discovery(videos={A: playlists.Video(A, "A"), B: playlists.Video(B, "B")})
    playlists.record_discovery(found, manifest, planned=False)
    calls: list[str] = []

    def fake_backup(url: str, output: Path, tools: Path, ffprobe: str, *, manifest: Manifest) -> Outcome:
        calls.append(url[-11:])
        manifest.fail(A, "download", "Sign in to confirm you're not a bot")
        manifest.save()
        return Outcome.FAILED

    monkeypatch.setattr(playlists, "backup_video", fake_backup)
    assert not playlists.run_queue(found, manifest, tmp_path, "ffprobe", sleep=lambda _: None)
    assert calls == [A] and Manifest.load(tmp_path).get(B)["status"] == "queued"


def test_rate_limit_waits_and_retries_at_most_three_times(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = Manifest.load(tmp_path)
    found = playlists.Discovery(videos={A: playlists.Video(A, "A")})
    playlists.record_discovery(found, manifest, planned=False)
    calls: list[str] = []
    waits: list[float] = []

    def fake_backup(url: str, output: Path, tools: Path, ffprobe: str, *, manifest: Manifest) -> Outcome:
        calls.append(url)
        manifest.fail(A, "download", "HTTP Error 429: Too Many Requests")
        return Outcome.FAILED

    monkeypatch.setattr(playlists, "backup_video", fake_backup)
    assert not playlists.run_queue(found, manifest, tmp_path, "ffprobe", sleep=waits.append)
    assert len(calls) == 4 and waits == [600, 600, 600]


def test_queue_does_not_retry_unresolved_quarantine_failure(tmp_path: Path,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = Manifest.load(tmp_path)
    manifest.fail(A, "verify", "permission denied", "quarantine_failed")
    found = playlists.Discovery(videos={A: playlists.Video(A, "A")})

    def forbidden(*args: object, **kwargs: object) -> Outcome:
        pytest.fail("unresolved quarantine failure was retried")

    monkeypatch.setattr(playlists, "backup_video", forbidden)
    assert not playlists.run_queue(found, manifest, tmp_path, "ffprobe", sleep=lambda _: None)


def test_cli_preview_cancellation_never_runs_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                   capsys: pytest.CaptureFixture[str]) -> None:
    found = playlists.Discovery(videos={A: playlists.Video(A, "A", duration=12)}, playlist_count=1)
    monkeypatch.setattr(versions, "collect", lambda _: [versions.Component("ffprobe", "1")])
    monkeypatch.setattr(playlists, "discover", lambda *args, **kwargs: found)
    monkeypatch.setattr("builtins.input", lambda _: "n")

    def forbidden(*args: object, **kwargs: object) -> bool:
        pytest.fail("queue ran despite cancellation")

    monkeypatch.setattr(playlists, "run_queue", forbidden)
    assert cli.main(["--playlists", PAGE, "--include-other-channels",
                     "--output", str(tmp_path), "--log-dir", str(tmp_path / "logs")]) == 0
    assert "unique videos: 1" in capsys.readouterr().out
    assert Manifest.load(tmp_path).get(A)["status"] == "planned"


def test_cli_confirmation_processes_unique_queue_and_resumes(tmp_path: Path,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    found = playlists.Discovery(videos={A: playlists.Video(A, "A", memberships=[
        {"id": P1, "title": "First", "position": 1},
        {"id": P2, "title": "Second", "position": 2},
    ])}, playlist_count=2)
    monkeypatch.setattr(versions, "collect", lambda _: [versions.Component("ffprobe", "1")])
    monkeypatch.setattr(versions, "resolve_binary", lambda *args: Path("ffprobe"))
    monkeypatch.setattr(playlists, "discover", lambda *args, **kwargs: found)
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    calls: list[str] = []

    def fake_backup(url: str, output: Path, tools: Path, ffprobe: str, *, manifest: Manifest) -> Outcome:
        if manifest.is_complete(A):
            return Outcome.SKIPPED
        calls.append(url)
        path = output / "video.mkv"
        path.write_bytes(b"video")
        details_path = output / "details.json"
        details_path.write_text("{}", encoding="utf-8")
        manifest.set_status(A, Status.VERIFIED, saved={"path": path.name}, details_path=details_path.name)
        manifest.save()
        return Outcome.VERIFIED

    monkeypatch.setattr(playlists, "backup_video", fake_backup)
    args = ["--playlists", PAGE, "--include-other-channels",
            "--output", str(tmp_path), "--log-dir", str(tmp_path / "logs")]
    assert cli.main(args) == 0
    assert cli.main(args) == 0
    assert calls == [f"https://www.youtube.com/watch?v={A}"]
    assert len(Manifest.load(tmp_path).get(A)["playlists"]) == 2
    assert len(json.loads((tmp_path / "details.json").read_text(encoding="utf-8"))["playlists"]) == 2
