"""Unit tests for dependency discovery (ytripper.versions)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ytripper import versions


@pytest.mark.parametrize(
    ("name", "output", "expected"),
    [
        ("ffmpeg", "ffmpeg version N-127541-gec33c154fa-20261014 Copyright (c) 2000-2026", "N-127541-gec33c154fa-20261014"),
        ("ffprobe", "ffprobe version 9.0.2-full_build-www.gyan.dev Copyright", "9.0.2-full_build-www.gyan.dev"),
        ("deno", "deno 2.9.7 (stable, release, x86_64-pc-windows-msvc)\nv8 14.5\ntypescript 5.9", "2.9.7"),
        ("ffmpeg", "garbage output", None),
        ("deno", "", None),
    ],
)
def test_parse_binary_version(name: str, output: str, expected: str | None) -> None:
    assert versions.parse_binary_version(name, output) == expected


def test_resolve_binary_prefers_tools_dir(tmp_path: Path) -> None:
    exe = tmp_path / "ffmpeg.exe"
    exe.write_bytes(b"")
    assert versions.resolve_binary("ffmpeg", tmp_path) == exe


def test_missing_binary_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(versions.shutil, "which", lambda _name: None)
    component = versions.binary_component("deno", tmp_path)
    assert not component.ok
    assert "not found" in (component.error or "")


def test_binary_component_runs_without_shell(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "deno.exe").write_bytes(b"")
    calls: list[dict] = []

    class _Result:
        stdout = "deno 2.9.7 (stable)"
        stderr = ""

    def fake_run(args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"args": args, **kwargs})
        return _Result()

    monkeypatch.setattr(versions.subprocess, "run", fake_run)
    component = versions.binary_component("deno", tmp_path)
    assert component.ok and component.version == "2.9.7"
    assert calls[0]["shell"] is False
    assert isinstance(calls[0]["args"], list)
    assert calls[0]["timeout"] > 0


def test_binary_component_handles_os_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "ffprobe.exe").write_bytes(b"")

    def boom(*_a, **_k):  # type: ignore[no-untyped-def]
        raise OSError("access denied")

    monkeypatch.setattr(versions.subprocess, "run", boom)
    component = versions.binary_component("ffprobe", tmp_path)
    assert not component.ok
    assert "access denied" in (component.error or "")


def test_missing_package_is_reported() -> None:
    component = versions.package_component("definitely-not-installed-ytripper-pkg")
    assert not component.ok


def test_collect_includes_every_required_component(tmp_path: Path) -> None:
    names = [c.name for c in versions.collect(tmp_path)]
    assert names[0] == "python"
    for required in (*versions.REQUIRED_PACKAGES, *versions.REQUIRED_BINARIES):
        assert required in names


def test_python_component_ok_on_supported_interpreter(tmp_path: Path) -> None:
    python = versions.collect(tmp_path)[0]
    assert python.ok == (sys.version_info >= (3, 10))


def test_format_report_marks_missing() -> None:
    report = versions.format_report(
        [versions.Component("ffmpeg", "9.0"), versions.Component("deno", None, error="deno not found")]
    )
    assert "OK" in report and "MISSING" in report and "deno not found" in report
