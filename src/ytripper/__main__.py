"""Command-line entry point: ``python -m ytripper``.

Increment 1 adds a temporary single-video mode (``--video URL --output DIR``)
used to validate the download -> verify -> manifest -> report slice. The
guided prompts replace it in Increment 5.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, versions
from .logging_setup import get_logger, setup_logging
from .paths import DEFAULT_LOG_DIR, PROJECT_ROOT, TOOLS_DIR

EXIT_OK = 0
EXIT_MISSING_DEPENDENCY = 3
EXIT_NOT_IMPLEMENTED = 4
EXIT_FAILURES = 5
EXIT_INVALID_INPUT = 2

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ytripper",
        description="Verified, best-quality backup of a YouTube channel.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--versions",
        action="store_true",
        help="check that all dependencies are present and print their versions",
    )
    modes.add_argument("--video", metavar="URL", help="back up a single video (temporary test mode)")
    modes.add_argument("--playlist", metavar="URL", help="back up one YouTube playlist")
    modes.add_argument("--playlists", metavar="URL", help="back up playlists on a channel's playlists page")
    parser.add_argument(
        "--include-other-channels", action="store_true",
        help="include videos from other channels when using --playlists",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"backup output folder (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=DEFAULT_LOG_DIR,
        help=f"directory for run logs (default: {DEFAULT_LOG_DIR})",
    )
    parser.add_argument(
        "--tools-dir",
        type=Path,
        default=TOOLS_DIR,
        help=f"directory containing ffmpeg/ffprobe/deno (default: {TOOLS_DIR})",
    )
    return parser


def cmd_versions(tools_dir: Path) -> int:
    """Print dependency versions; non-zero exit if anything is missing."""
    log = get_logger("versions")
    components = versions.collect(tools_dir)
    print(versions.format_report(components))
    for c in components:
        log.debug("dependency %s version=%s location=%s error=%s", c.name, c.version, c.location, c.error)
    missing = [c.name for c in components if not c.ok]
    if missing:
        log.error("Missing dependencies: %s. Run setup.ps1 to install them.", ", ".join(missing))
        return EXIT_MISSING_DEPENDENCY
    return EXIT_OK


def cmd_video(url: str, output_dir: Path, tools_dir: Path) -> int:
    """Back up one video and report the outcome."""
    from .manifest import Manifest, ManifestError
    from .pipeline import Outcome, backup_video

    log = get_logger()
    components = versions.collect(tools_dir)
    missing = [c.name for c in components if not c.ok]
    if missing:
        log.error("Missing dependencies: %s. Run setup.ps1 first.", ", ".join(missing))
        return EXIT_MISSING_DEPENDENCY

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest = Manifest.load(output_dir)
    except (OSError, ManifestError) as exc:
        log.error("Cannot use output folder %s: %s", output_dir, exc)
        return EXIT_INVALID_INPUT
    manifest.record_run({c.name: c.version for c in components})

    ffprobe = versions.resolve_binary("ffprobe", tools_dir)
    outcome = backup_video(url, output_dir, tools_dir, str(ffprobe), manifest=manifest)
    log.info("Result: %s  (manifest: %s)", outcome.value, output_dir / "manifest.json")
    if outcome is Outcome.INVALID:
        return EXIT_INVALID_INPUT
    return EXIT_OK if outcome in (Outcome.VERIFIED, Outcome.SKIPPED) else EXIT_FAILURES


def cmd_playlists(url: str, output_dir: Path, tools_dir: Path, *, page: bool,
                  include_other_channels: bool) -> int:
    """Discover, preview and back up a playlist or channel playlists page."""
    from .manifest import Manifest, ManifestError
    from .playlists import DiscoveryError, discover, preview, record_discovery, run_queue

    log = get_logger()
    components = versions.collect(tools_dir)
    missing = [c.name for c in components if not c.ok]
    if missing:
        log.error("Missing dependencies: %s. Run setup.ps1 first.", ", ".join(missing))
        return EXIT_MISSING_DEPENDENCY
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest = Manifest.load(output_dir)
        discovery = discover(url, page=page, include_other_channels=include_other_channels, tools_dir=tools_dir)
        preview(discovery, manifest)
        if not discovery.videos:
            log.error("No videos could be queued; no download was started.")
            return EXIT_FAILURES
        try:
            answer = input("Download these videos? [y/N] ").strip().lower()
        except EOFError:
            log.error("No confirmation available; no download was started.")
            answer = ""
        manifest.record_run({c.name: c.version for c in components})
        record_discovery(discovery, manifest, planned=answer not in ("y", "yes"))
        if answer not in ("y", "yes"):
            log.info("Download cancelled; newly discovered videos were recorded as planned.")
            return EXIT_OK
        ffprobe = versions.resolve_binary("ffprobe", tools_dir)
        return EXIT_OK if run_queue(discovery, manifest, tools_dir, str(ffprobe)) else EXIT_FAILURES
    except (OSError, ManifestError, DiscoveryError) as exc:
        log.error("Playlist backup failed: %s", exc)
        return EXIT_FAILURES


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.include_other_channels and not args.playlists:
        build_parser().error("--include-other-channels requires --playlists")
    try:
        log_path = setup_logging(args.log_dir)
    except OSError as exc:
        print(f"ERROR: cannot create log directory {args.log_dir}: {exc}", file=sys.stderr)
        return 1
    log = get_logger()
    log.debug("ytripper %s, argv=%s, log=%s", __version__, argv if argv is not None else sys.argv[1:], log_path)

    if args.versions:
        return cmd_versions(args.tools_dir)
    if args.video:
        return cmd_video(args.video, args.output, args.tools_dir)
    if args.playlist or args.playlists:
        return cmd_playlists(args.playlist or args.playlists, args.output, args.tools_dir,
                             page=bool(args.playlists), include_other_channels=args.include_other_channels)

    log.info("The guided backup is not implemented yet (planned for Increment 5).")
    log.info("Use --versions, --video URL, --playlist URL, or --playlists URL.")
    return EXIT_NOT_IMPLEMENTED


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
