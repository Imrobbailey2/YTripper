"""Dependency discovery and version reporting.

Used by ``setup.ps1`` (via ``python -m ytripper --versions``) to prove the
environment is complete, and recorded in every run log for traceability
(NF10). External binaries are resolved from the project ``tools`` directory
first, then ``PATH``. Subprocesses are always invoked with an argument list
(never through a shell) and a timeout.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from .paths import TOOLS_DIR

#: Python packages that must be importable inside the virtual environment.
REQUIRED_PACKAGES: tuple[str, ...] = ("yt-dlp", "yt-dlp-ejs", "rich")

#: External executables -> argument that prints the version.
REQUIRED_BINARIES: dict[str, list[str]] = {
    "ffmpeg": ["-version"],
    "ffprobe": ["-version"],
    "deno": ["--version"],
}

_FFMPEG_RE = re.compile(r"^ff(?:mpeg|probe) version (\S+)", re.MULTILINE)
_DENO_RE = re.compile(r"^deno (\S+)", re.MULTILINE)
_SUBPROCESS_TIMEOUT_S = 20


@dataclass(frozen=True)
class Component:
    """A dependency and what was found for it."""

    name: str
    version: str | None
    location: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.version is not None


def parse_binary_version(name: str, output: str) -> str | None:
    """Extract a version string from ``ffmpeg``/``ffprobe``/``deno`` output."""
    pattern = _DENO_RE if name == "deno" else _FFMPEG_RE
    match = pattern.search(output)
    return match.group(1) if match else None


def resolve_binary(name: str, tools_dir: Path = TOOLS_DIR) -> Path | None:
    """Locate an executable, preferring the project tools directory."""
    for candidate in (tools_dir / f"{name}.exe", tools_dir / name):
        if candidate.is_file():
            return candidate
    found = shutil.which(name)
    return Path(found) if found else None


def binary_component(name: str, tools_dir: Path = TOOLS_DIR) -> Component:
    """Probe one external executable and report its version."""
    path = resolve_binary(name, tools_dir)
    if path is None:
        return Component(name, None, error=f"{name} not found in {tools_dir} or PATH")
    try:
        result = subprocess.run(  # noqa: S603 - fixed argument list, no shell
            [str(path), *REQUIRED_BINARIES[name]],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_SUBPROCESS_TIMEOUT_S,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Component(name, None, str(path), error=f"failed to run: {exc}")
    version = parse_binary_version(name, result.stdout + result.stderr)
    if version is None:
        return Component(name, None, str(path), error="could not parse version output")
    return Component(name, version, str(path))


def package_component(name: str) -> Component:
    """Report the installed version of a Python distribution."""
    try:
        return Component(name, metadata.version(name), "python package")
    except metadata.PackageNotFoundError:
        return Component(name, None, error=f"Python package '{name}' is not installed")


def collect(tools_dir: Path = TOOLS_DIR) -> list[Component]:
    """Return all required components, Python first."""
    python = Component(
        "python",
        platform.python_version(),
        sys.executable,
        error=None,
    )
    if sys.version_info < (3, 10):
        python = Component("python", None, sys.executable, error="Python 3.10+ required")
    return [
        python,
        *(package_component(p) for p in REQUIRED_PACKAGES),
        *(binary_component(b, tools_dir) for b in REQUIRED_BINARIES),
    ]


def format_report(components: list[Component]) -> str:
    """Render components as an aligned plain-text table."""
    width = max(len(c.name) for c in components)
    lines = []
    for c in components:
        status = "OK     " if c.ok else "MISSING"
        detail = c.version if c.ok else c.error
        lines.append(f"{status} {c.name.ljust(width)}  {detail}")
    return "\n".join(lines)
