"""Per-output-folder state ledger (``manifest.json``).

The manifest is the single source of truth for each video's status
(architecture decision 2). A video only counts as done once it is
``verified``. Writes are atomic: the new content goes to a temporary file
which then replaces the old one, and the previous version is kept as
``manifest.json.bak`` so an interrupted write can never lose state.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .logging_setup import get_logger

MANIFEST_NAME = "manifest.json"
SCHEMA_VERSION = 1

log = get_logger("manifest")


class Status(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    VERIFIED = "verified"
    FAILED = "failed"
    PLANNED = "planned"


class ManifestError(Exception):
    """Raised when neither the manifest nor its backup can be read."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Manifest:
    """In-memory view of ``manifest.json`` with atomic persistence."""

    def __init__(self, output_dir: Path, data: dict[str, Any] | None = None) -> None:
        self.output_dir = output_dir
        self.path = output_dir / MANIFEST_NAME
        self.data: dict[str, Any] = data or {
            "schema": SCHEMA_VERSION,
            "run_meta": {"created": _now(), "last_run": None, "tool_versions": {}},
            "videos": {},
        }

    # ----------------------------------------------------------------- I/O
    @classmethod
    def load(cls, output_dir: Path) -> "Manifest":
        """Load the manifest (falling back to the backup) or start a new one.

        Any video left in ``downloading`` by an interrupted run is reset to
        ``queued`` so it will be retried.
        """
        path = output_dir / MANIFEST_NAME
        backup = path.with_suffix(".json.bak")
        data: dict[str, Any] | None = None
        for candidate in (path, backup):
            if not candidate.exists():
                continue
            try:
                loaded = json.loads(candidate.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict) or not isinstance(loaded.get("videos"), dict):
                    raise ValueError("unexpected structure")
                data = loaded
                if candidate is backup:
                    log.warning("manifest.json was unreadable; recovered from %s", backup.name)
                break
            except (OSError, ValueError) as exc:
                log.error("Could not read %s: %s", candidate, exc)
        else:
            if path.exists() or backup.exists():
                raise ManifestError(f"{path} and its backup are both unreadable")

        manifest = cls(output_dir, data)
        for vid, entry in manifest.videos.items():
            if entry.get("status") == Status.DOWNLOADING.value:
                log.warning("%s was interrupted during download; re-queued", vid)
                entry["status"] = Status.QUEUED.value
        return manifest

    def save(self) -> None:
        """Atomically write the manifest, keeping the previous copy as .bak."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        payload = json.dumps(self.data, indent=2, ensure_ascii=False, sort_keys=True)
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        if self.path.exists():
            shutil.copy2(self.path, self.path.with_suffix(".json.bak"))
        os.replace(tmp, self.path)

    # -------------------------------------------------------------- access
    @property
    def videos(self) -> dict[str, dict[str, Any]]:
        return self.data["videos"]

    def get(self, video_id: str) -> dict[str, Any] | None:
        return self.videos.get(video_id)

    def ensure(self, video_id: str, **fields: Any) -> dict[str, Any]:
        """Return the entry for *video_id*, creating a queued one if missing."""
        entry = self.videos.setdefault(
            video_id,
            {"status": Status.QUEUED.value, "attempts": 0, "last_error": None, "created": _now()},
        )
        entry.update({k: v for k, v in fields.items() if v is not None})
        entry["updated"] = _now()
        return entry

    def set_status(self, video_id: str, status: Status, **fields: Any) -> dict[str, Any]:
        entry = self.ensure(video_id, **fields)
        entry["status"] = status.value
        if status is Status.DOWNLOADING:
            entry["attempts"] = int(entry.get("attempts", 0)) + 1
        if status in (Status.VERIFIED, Status.DOWNLOADED):
            entry["last_error"] = None
        return entry

    def fail(self, video_id: str, stage: str, message: str, code: str = "error") -> dict[str, Any]:
        entry = self.set_status(video_id, Status.FAILED)
        entry["last_error"] = {"stage": stage, "code": code, "message": message}
        return entry

    def is_complete(self, video_id: str) -> bool:
        """True if the video is verified and its saved file still exists."""
        entry = self.get(video_id)
        if not entry or entry.get("status") != Status.VERIFIED.value:
            return False
        rel = (entry.get("saved") or {}).get("path")
        return bool(rel) and (self.output_dir / rel).is_file()

    def record_run(self, tool_versions: dict[str, str | None]) -> None:
        meta = self.data.setdefault("run_meta", {})
        meta["last_run"] = _now()
        meta["tool_versions"] = tool_versions
