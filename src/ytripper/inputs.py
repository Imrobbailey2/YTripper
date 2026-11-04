"""Lists of video links: a text file or pasted lines (F4).

File rules: UTF-8 (a byte-order mark is allowed), one link per line, blank
lines and ``#`` comments ignored. Pasted rules: the same, but input ends at
the first blank line. Every line that can't be used is reported with its line
number so it can be fixed before the preview.

Pure functions only: no network and no yt-dlp import.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, TextIO

from .urls import Link, LinkError, LinkKind, classify_url

#: A list file bigger than this is almost certainly not a list of links.
MAX_LIST_FILE_BYTES = 5 * 1024 * 1024
#: Longest line accepted as a link.
MAX_LINE_CHARS = 2048

#: Invisible characters that copy-and-paste from browsers, Word or Teams can add.
_INVISIBLE_RE = re.compile("[\ufeff\u200b\u200c\u200d\u2060]")
#: "link  # note": a # preceded by whitespace starts a comment (a # inside a URL does not).
_INLINE_COMMENT_RE = re.compile(r"\s#.*$")
#: Wrapping characters to remove: quotes and angle brackets.
_WRAPPERS = "\"'<>\u201c\u201d\u2018\u2019"


@dataclass(frozen=True)
class ListEntry:
    """A usable link and the line it came from (1-based)."""

    line_no: int
    text: str
    link: Link


@dataclass(frozen=True)
class ListError:
    """A line that can't be used, with the reason."""

    line_no: int
    text: str
    reason: str

    def __str__(self) -> str:
        shown = self.text if len(self.text) <= 80 else self.text[:77] + "..."
        return f"line {self.line_no}: {self.reason}: {shown}"


@dataclass
class ParsedList:
    """Result of reading a list: usable entries and line-numbered errors."""

    entries: list[ListEntry] = field(default_factory=list)
    errors: list[ListError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when every non-blank, non-comment line is a usable link."""
        return not self.errors

    @property
    def links(self) -> list[Link]:
        return [entry.link for entry in self.entries]


class ListFileError(Exception):
    """The list file itself can't be read; ``str(exc)`` is the plain-language reason."""


def clean_line(raw: str) -> str:
    """Return the link text on a line, or "" for a blank or comment-only line."""
    text = _INVISIBLE_RE.sub("", raw).strip()
    if text.startswith("#"):
        return ""
    text = _INLINE_COMMENT_RE.sub("", text).strip()
    return text.strip(_WRAPPERS).strip()


def _check_line(line_no: int, raw: str, allowed: frozenset[LinkKind]) -> ListEntry | ListError:
    text = clean_line(raw)
    if len(text) > MAX_LINE_CHARS:
        return ListError(line_no, text, "the line is too long to be a link")
    if any(ch.isspace() for ch in text):
        return ListError(line_no, text, "more than one item on this line (put one link per line)")
    try:
        link = classify_url(text)
    except LinkError as exc:
        return ListError(line_no, text, str(exc))
    if link.kind not in allowed:
        return ListError(line_no, text, f"this is a {link.kind.value} link, but a list may only contain video links")
    return ListEntry(line_no, text, link)


def parse_lines(
    lines: Iterable[str],
    *,
    stop_at_blank: bool = False,
    allowed: Iterable[LinkKind] = (LinkKind.VIDEO,),
) -> ParsedList:
    """Check each line; blank lines and ``#`` comments are skipped.

    Args:
        lines: the lines, numbered from 1. Trailing newlines are allowed.
        stop_at_blank: stop at the first blank line (pasted input). The input is
            read lazily, so nothing after that line is consumed.
        allowed: link kinds a line may contain (only video links by default).
    """
    kinds = frozenset(allowed)
    result = ParsedList()
    for line_no, raw in enumerate(lines, start=1):
        if not _INVISIBLE_RE.sub("", raw).strip():
            if stop_at_blank:
                break
            continue
        if not clean_line(raw):
            continue
        checked = _check_line(line_no, raw, kinds)
        if isinstance(checked, ListEntry):
            result.entries.append(checked)
        else:
            result.errors.append(checked)
    return result


def split_lines(text: str) -> list[str]:
    """Split on CRLF, CR or LF only, so line numbers match what a text editor shows."""
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def decode_list_bytes(data: bytes) -> str:
    """Decode a list file as UTF-8 (byte-order mark allowed).

    Raises:
        ListFileError: if the bytes are UTF-16 or otherwise not UTF-8 text.
    """
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise ListFileError('the file is saved as UTF-16 ("Unicode"); save it again as UTF-8')
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ListFileError("the file is not UTF-8 text; in Notepad use File > Save as, Encoding: UTF-8") from None


def read_list_file(path: Path) -> ParsedList:
    """Read a list file of video links.

    Raises:
        ListFileError: if the file is missing, too large, unreadable or not UTF-8.
    """
    try:
        if not path.exists():
            raise ListFileError(f"file not found: {path}")
        if not path.is_file():
            raise ListFileError(f"not a file: {path}")
        size = path.stat().st_size
        if size > MAX_LIST_FILE_BYTES:
            raise ListFileError(f"the file is {size:,} bytes; a list of links should be far smaller than 5 MB")
        data = path.read_bytes()
    except OSError as exc:
        raise ListFileError(f"cannot read {path}: {exc.strerror or exc}") from exc
    return parse_lines(split_lines(decode_list_bytes(data)))


def _stream_lines(stream: TextIO) -> Iterator[str]:
    for line in stream:
        yield line


def read_pasted(stream: TextIO) -> ParsedList:
    """Read pasted video links from *stream* until the first blank line or end of input."""
    return parse_lines(_stream_lines(stream), stop_at_blank=True)
