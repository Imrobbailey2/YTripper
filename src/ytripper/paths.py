"""Project path helpers.

All locations are resolved relative to the repository root so the script
behaves the same regardless of the current working directory.
"""

from __future__ import annotations

from pathlib import Path

#: Repository root (…/YTripper). ``src/ytripper/paths.py`` -> parents[2].
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]

#: Directory holding ffmpeg.exe, ffprobe.exe and deno.exe (populated by setup.ps1).
TOOLS_DIR: Path = PROJECT_ROOT / "tools"

#: Default directory for run logs.
DEFAULT_LOG_DIR: Path = PROJECT_ROOT / "logs"
