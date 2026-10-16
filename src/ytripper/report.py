"""CSV report generated from the manifest (F11).

Written as UTF-8 with a BOM so Excel opens non-ASCII titles correctly.
Later increments add description and playlist columns.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

from .manifest import Manifest

REPORT_NAME = "report.csv"
COLUMNS = (
    "video_id", "title", "channel", "status", "height", "fps", "vcodec", "acodec",
    "duration_s", "size_bytes", "path", "attempts", "error",
)


def build_rows(manifest: Manifest) -> list[dict[str, object]]:
    rows = []
    for vid in sorted(manifest.videos):
        entry = manifest.videos[vid]
        saved = entry.get("saved") or {}
        err = entry.get("last_error") or {}
        rows.append({
            "video_id": vid,
            "title": entry.get("title", ""),
            "channel": entry.get("channel", ""),
            "status": entry.get("status", ""),
            "height": saved.get("height", ""),
            "fps": saved.get("fps", ""),
            "vcodec": saved.get("vcodec", ""),
            "acodec": saved.get("acodec", ""),
            "duration_s": saved.get("duration_s", ""),
            "size_bytes": saved.get("size_bytes", ""),
            "path": saved.get("path", ""),
            "attempts": entry.get("attempts", 0),
            "error": f"{err.get('stage')}: {err.get('message')}" if err else "",
        })
    return rows


def write_report(manifest: Manifest) -> Path:
    """Write ``report.csv`` next to the manifest (atomically) and return its path."""
    path = manifest.output_dir / REPORT_NAME
    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(build_rows(manifest))
    os.replace(tmp, path)
    return path
