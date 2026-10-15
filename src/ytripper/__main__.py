"""Command-line entry point: ``python -m ytripper``.

Increment 0 provides only ``--versions`` (environment check used by
setup.ps1). The guided backup flow is added in later increments.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, versions
from .logging_setup import get_logger, setup_logging
from .paths import DEFAULT_LOG_DIR, TOOLS_DIR

EXIT_OK = 0
EXIT_MISSING_DEPENDENCY = 3
EXIT_NOT_IMPLEMENTED = 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ytripper",
        description="Verified, best-quality backup of a YouTube channel.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--versions",
        action="store_true",
        help="check that all dependencies are present and print their versions",
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        log_path = setup_logging(args.log_dir)
    except OSError as exc:
        print(f"ERROR: cannot create log directory {args.log_dir}: {exc}", file=sys.stderr)
        return 1
    log = get_logger()
    log.debug("ytripper %s, argv=%s, log=%s", __version__, argv if argv is not None else sys.argv[1:], log_path)

    if args.versions:
        return cmd_versions(args.tools_dir)

    log.info("The guided backup is not implemented yet (planned for a later increment).")
    log.info("Use --versions to check the environment.")
    return EXIT_NOT_IMPLEMENTED


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
