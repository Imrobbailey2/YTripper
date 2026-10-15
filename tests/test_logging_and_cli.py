"""Tests for run logging (NF7) and the CLI skeleton."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ytripper import __main__ as cli
from ytripper import versions
from ytripper.logging_setup import get_logger, run_log_name, setup_logging


def test_run_log_name_is_utc_timestamped() -> None:
    name = run_log_name(datetime(2026, 10, 15, 17, 35, 0, tzinfo=timezone.utc))
    assert name == "run-20261015T173500Z.log"


def test_setup_logging_writes_file(tmp_path: Path) -> None:
    log_path = setup_logging(tmp_path / "logs")
    get_logger("test").info("hello log")
    for handler in get_logger().handlers:
        handler.flush()
    content = log_path.read_text(encoding="utf-8")
    assert "hello log" in content
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", content)


def test_setup_logging_does_not_duplicate_handlers(tmp_path: Path) -> None:
    setup_logging(tmp_path)
    setup_logging(tmp_path)
    assert len(get_logger().handlers) == 2


def test_cli_versions_fails_when_dependency_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        versions, "collect", lambda _tools: [versions.Component("ffmpeg", None, error="ffmpeg not found")]
    )
    code = cli.main(["--versions", "--log-dir", str(tmp_path)])
    assert code == cli.EXIT_MISSING_DEPENDENCY


def test_cli_versions_succeeds_when_all_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        versions, "collect", lambda _tools: [versions.Component("ffmpeg", "9.0"), versions.Component("deno", "2.9.7")]
    )
    code = cli.main(["--versions", "--log-dir", str(tmp_path)])
    assert code == cli.EXIT_OK
    assert "2.9.7" in capsys.readouterr().out


def test_cli_without_arguments_reports_not_implemented(tmp_path: Path) -> None:
    assert cli.main(["--log-dir", str(tmp_path)]) == cli.EXIT_NOT_IMPLEMENTED
