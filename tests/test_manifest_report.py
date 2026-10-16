"""Tests for the manifest ledger and CSV report."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from ytripper.manifest import Manifest, ManifestError, Status
from ytripper.report import COLUMNS, write_report


def test_new_manifest_round_trip(tmp_path: Path) -> None:
    m = Manifest.load(tmp_path)
    m.set_status("abcdefghijk", Status.DOWNLOADING, title="T")
    m.save()
    again = Manifest.load(tmp_path)
    # interrupted download is re-queued on load
    assert again.get("abcdefghijk")["status"] == Status.QUEUED.value
    assert again.get("abcdefghijk")["attempts"] == 1


def test_save_is_atomic_and_keeps_backup(tmp_path: Path) -> None:
    m = Manifest.load(tmp_path)
    m.ensure("aaaaaaaaaaa")
    m.save()
    m.ensure("bbbbbbbbbbb")
    m.save()
    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "manifest.json.bak").exists()
    assert not (tmp_path / "manifest.json.tmp").exists()
    backup = json.loads((tmp_path / "manifest.json.bak").read_text(encoding="utf-8"))
    assert "aaaaaaaaaaa" in backup["videos"] and "bbbbbbbbbbb" not in backup["videos"]


def test_corrupt_manifest_recovers_from_backup(tmp_path: Path) -> None:
    m = Manifest.load(tmp_path)
    m.ensure("aaaaaaaaaaa")
    m.save()
    m.save()  # creates .bak with the same content
    (tmp_path / "manifest.json").write_text("{ truncated", encoding="utf-8")
    recovered = Manifest.load(tmp_path)
    assert "aaaaaaaaaaa" in recovered.videos


def test_corrupt_manifest_without_backup_raises(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text("not json", encoding="utf-8")
    with pytest.raises(ManifestError):
        Manifest.load(tmp_path)


def test_is_complete_requires_existing_file(tmp_path: Path) -> None:
    m = Manifest.load(tmp_path)
    m.set_status("aaaaaaaaaaa", Status.VERIFIED, saved={"path": "ch/v.mkv"})
    assert not m.is_complete("aaaaaaaaaaa")
    (tmp_path / "ch").mkdir()
    (tmp_path / "ch" / "v.mkv").write_bytes(b"x")
    assert m.is_complete("aaaaaaaaaaa")


def test_fail_records_error_and_verified_clears_it(tmp_path: Path) -> None:
    m = Manifest.load(tmp_path)
    m.fail("aaaaaaaaaaa", "download", "HTTP 403", "http")
    assert m.get("aaaaaaaaaaa")["last_error"]["stage"] == "download"
    m.set_status("aaaaaaaaaaa", Status.VERIFIED)
    assert m.get("aaaaaaaaaaa")["last_error"] is None


def test_report_has_row_per_video_and_bom(tmp_path: Path) -> None:
    m = Manifest.load(tmp_path)
    m.set_status("aaaaaaaaaaa", Status.VERIFIED, title="Ünïcode title",
                 saved={"height": 1080, "fps": 30.0, "path": "a.mkv"})
    m.fail("bbbbbbbbbbb", "verify", "no audio stream")
    path = write_report(m)
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines()))
    assert [r["video_id"] for r in rows] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    assert rows[0]["title"] == "Ünïcode title" and rows[0]["height"] == "1080"
    assert rows[1]["error"] == "verify: no audio stream"
    assert tuple(rows[0].keys()) == COLUMNS
