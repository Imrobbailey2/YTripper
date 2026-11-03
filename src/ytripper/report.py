"""CSV report generated from the manifest (F11, F19).

Written as UTF-8 with a BOM so Excel opens non-ASCII titles correctly.
Text that comes from YouTube (titles, channel, author, errors) is untrusted:
any cell starting with a formula trigger is prefixed with ``'`` so Excel
shows it as text instead of evaluating it (CSV/formula injection, CWE-1236).
Playlist columns are added in Increment 3.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

from .manifest import Manifest

REPORT_NAME = "report.csv"
COLUMNS = (
    "video_id", "title", "channel", "status", "height", "fps", "vcodec", "acodec",
    "duration_s", "size_bytes", "path",
    "author", "author_source", "chapter_count", "hashtag_count", "link_count",
    "attempts", "error",
)

#: Leading characters that make Excel/LibreOffice treat a cell as a formula.
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: object) -> object:
    """Neutralise spreadsheet formula injection in a text cell; other types pass through."""
    if isinstance(value, str) and value.startswith(_FORMULA_TRIGGERS):
        return "'" + value
    return value


def build_rows(manifest: Manifest) -> list[dict[str, object]]:
    rows = []
    for vid in sorted(manifest.videos):
        entry = manifest.videos[vid]
        saved = entry.get("saved") or {}
        details = entry.get("details") or {}
        err = entry.get("last_error") or {}
        row = {
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
            "author": details.get("author", ""),
            "author_source": details.get("author_source", ""),
            "chapter_count": details.get("chapter_count", ""),
            "hashtag_count": details.get("hashtag_count", ""),
            "link_count": details.get("link_count", ""),
            "attempts": entry.get("attempts", 0),
            "error": f"{err.get('stage')}: {err.get('message')}" if err else "",
        }
        rows.append({key: safe_cell(value) for key, value in row.items()})
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
