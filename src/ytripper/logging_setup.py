"""Run logging (NF7).

Every run writes a timestamped UTF-8 log file at DEBUG level, while the
console shows INFO and above. Re-initialising replaces previous handlers so
repeated calls (e.g. in tests) never duplicate output.
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

LOGGER_NAME = "ytripper"
_FILE_FORMAT = "%(asctime)s.%(msecs)03dZ %(levelname)-8s %(name)s: %(message)s"
_CONSOLE_FORMAT = "%(levelname)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


class _UTCFormatter(logging.Formatter):
    """Formatter that renders each record's own timestamp in UTC."""

    converter = time.gmtime


def run_log_name(now: datetime | None = None) -> str:
    """Return the log file name for a run, e.g. ``run-20261015T173500Z.log``."""
    now = now or datetime.now(timezone.utc)
    return f"run-{now.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}.log"


def setup_logging(log_dir: Path, console_level: int = logging.INFO) -> Path:
    """Configure the ``ytripper`` logger and return the path of the run log.

    Args:
        log_dir: Directory for log files; created if missing.
        console_level: Minimum level echoed to the console.

    Raises:
        OSError: If the log directory or file cannot be created.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / run_log_name()

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(_UTCFormatter(_FILE_FORMAT, _DATE_FORMAT))

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(logging.Formatter(_CONSOLE_FORMAT))

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.debug("Logging initialised: %s", log_path)
    return log_path


def get_logger(name: str | None = None) -> logging.Logger:
    """Return the project logger or a named child of it."""
    return logging.getLogger(LOGGER_NAME if not name else f"{LOGGER_NAME}.{name}")
