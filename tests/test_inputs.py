"""Tests for link lists from a file or pasted input (F4)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from ytripper import inputs
from ytripper.inputs import (
    ListFileError,
    clean_line,
    parse_lines,
    read_list_file,
    read_pasted,
    split_lines,
)
from ytripper.urls import LinkKind

A = "_hqB_JFI3e8"
B = "qptE9mFsYbw"
C = "dQw4w9WgXcQ"
PLAYLIST = "PLPPUs8ihmoypPkhnDP3CGkRlsf-o8lje4"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (f"https://youtu.be/{A}\n", f"https://youtu.be/{A}"),
        (f"  https://youtu.be/{A}  \r\n", f"https://youtu.be/{A}"),
        ("# a comment", ""),
        ("   # indented comment", ""),
        (f"https://youtu.be/{A}   # client intro", f"https://youtu.be/{A}"),
        (f"https://www.youtube.com/watch?v={A}#t=10", f"https://www.youtube.com/watch?v={A}#t=10"),
        (f"\ufeffhttps://youtu.be/{A}", f"https://youtu.be/{A}"),
        (f"\u200bhttps://youtu.be/{A}\u200b", f"https://youtu.be/{A}"),
        (f"<https://youtu.be/{A}>", f"https://youtu.be/{A}"),
        (f"\"https://youtu.be/{A}\"", f"https://youtu.be/{A}"),
        (f"\u201chttps://youtu.be/{A}\u201d", f"https://youtu.be/{A}"),
        (f"\u00a0https://youtu.be/{A}\u00a0", f"https://youtu.be/{A}"),
        ("", ""),
    ],
)
def test_clean_line(raw: str, expected: str) -> None:
    assert clean_line(raw) == expected


def test_parse_lines_skips_blanks_and_comments_and_numbers_lines() -> None:
    lines = [
        "# Client videos",
        f"https://youtu.be/{A}",
        "",
        f"https://www.youtube.com/watch?v={B}&si=x   # keynote",
        "   ",
        f"https://www.youtube.com/shorts/{C}",
    ]
    result = parse_lines(lines)
    assert result.ok
    assert [(e.line_no, e.link.key) for e in result.entries] == [(2, A), (4, B), (6, C)]
    assert all(link.kind is LinkKind.VIDEO for link in result.links)


def test_parse_lines_reports_each_bad_line_with_its_number() -> None:
    lines = [
        f"https://youtu.be/{A}",
        "https://vimeo.com/123",
        f"https://youtu.be/{B} https://youtu.be/{C}",
        "https://www.youtube.com/watch?v=short",
        f"https://www.youtube.com/playlist?list={PLAYLIST}",
        "https://www.youtube.com/@UFIFAS",
        "x" * 3000,
    ]
    result = parse_lines(lines)
    assert not result.ok
    assert [e.link.key for e in result.entries] == [A]
    errors = {e.line_no: e.reason for e in result.errors}
    assert set(errors) == {2, 3, 4, 5, 6, 7}
    assert "not a YouTube link" in errors[2]
    assert "one link per line" in errors[3]
    assert "video ID" in errors[4]
    assert "playlist link" in errors[5] and "only contain video links" in errors[5]
    assert "channel link" in errors[6]
    assert "too long" in errors[7]


def test_list_error_str_names_the_line_and_truncates_long_text() -> None:
    result = parse_lines(["", "https://vimeo.com/" + "9" * 200])
    message = str(result.errors[0])
    assert message.startswith("line 2: this is not a YouTube link: https://vimeo.com/")
    assert message.endswith("...") and len(message) < 160


def test_parse_lines_keeps_duplicates_for_later_deduplication() -> None:
    # F4a de-duplication happens when sources are merged (step 3), not here.
    result = parse_lines([f"https://youtu.be/{A}", f"https://www.youtube.com/watch?v={A}"])
    assert [e.link.key for e in result.entries] == [A, A]


def test_parse_lines_can_allow_other_kinds() -> None:
    result = parse_lines([f"https://www.youtube.com/playlist?list={PLAYLIST}"],
                         allowed=(LinkKind.VIDEO, LinkKind.PLAYLIST))
    assert result.ok and result.links[0].kind is LinkKind.PLAYLIST


def test_parse_lines_empty_input() -> None:
    result = parse_lines(["", "# only comments", "   "])
    assert result.ok and result.entries == [] and result.links == []


def test_split_lines_matches_editor_line_numbers() -> None:
    # \x0b, \x1c and \u2028 would split under str.splitlines() and shift the numbering.
    assert split_lines("a\r\nb\rc\nd\u2028e\x0bf") == ["a", "b", "c", "d\u2028e\x0bf"]


# ------------------------------------------------------------------- files
def _write(tmp_path: Path, data: bytes, name: str = "links.txt") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_read_list_file_utf8_with_bom_and_crlf(tmp_path: Path) -> None:
    body = f"# Café talks\r\nhttps://youtu.be/{A}\r\n\r\nhttps://youtu.be/{B}\r\n"
    path = _write(tmp_path, b"\xef\xbb\xbf" + body.encode("utf-8"))
    result = read_list_file(path)
    assert result.ok
    assert [(e.line_no, e.link.key) for e in result.entries] == [(2, A), (4, B)]


def test_read_list_file_without_bom_or_final_newline(tmp_path: Path) -> None:
    path = _write(tmp_path, f"https://youtu.be/{A}\nnot a link".encode("utf-8"))
    result = read_list_file(path)
    assert [e.link.key for e in result.entries] == [A]
    assert [(e.line_no, e.text) for e in result.errors] == [(2, "not a link")]


def test_read_list_file_errors_keep_file_line_numbers_with_blank_lines(tmp_path: Path) -> None:
    path = _write(tmp_path, b"\n\n\nbad\n")
    assert read_list_file(path).errors[0].line_no == 4


def test_read_list_file_rejects_utf16(tmp_path: Path) -> None:
    path = _write(tmp_path, f"https://youtu.be/{A}".encode("utf-16"))
    with pytest.raises(ListFileError, match="UTF-16"):
        read_list_file(path)


def test_read_list_file_rejects_non_utf8(tmp_path: Path) -> None:
    path = _write(tmp_path, "Caf\u00e9 https://youtu.be/x".encode("cp1252"))
    with pytest.raises(ListFileError, match="not UTF-8"):
        read_list_file(path)


def test_read_list_file_missing_and_folder(tmp_path: Path) -> None:
    with pytest.raises(ListFileError, match="file not found"):
        read_list_file(tmp_path / "nope.txt")
    with pytest.raises(ListFileError, match="not a file"):
        read_list_file(tmp_path)


def test_read_list_file_rejects_huge_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inputs, "MAX_LIST_FILE_BYTES", 10)
    path = _write(tmp_path, b"x" * 11)
    with pytest.raises(ListFileError, match="5 MB"):
        read_list_file(path)


# ------------------------------------------------------------------ pasted
def test_read_pasted_stops_at_first_blank_line_without_reading_further() -> None:
    stream = io.StringIO(f"https://youtu.be/{A}\n# note\nhttps://youtu.be/{B}\n\nhttps://youtu.be/{C}\n")
    result = read_pasted(stream)
    assert [e.link.key for e in result.entries] == [A, B]
    assert stream.readline() == f"https://youtu.be/{C}\n"  # left unread


def test_read_pasted_ends_at_eof_and_strips_bom() -> None:
    result = read_pasted(io.StringIO(f"\ufeffhttps://youtu.be/{A}\nbad"))
    assert [e.link.key for e in result.entries] == [A]
    assert [(e.line_no, e.text) for e in result.errors] == [(2, "bad")]


def test_read_pasted_whitespace_only_line_ends_input() -> None:
    result = read_pasted(io.StringIO(f"https://youtu.be/{A}\n  \t \nhttps://youtu.be/{B}\n"))
    assert [e.link.key for e in result.entries] == [A]


def test_read_pasted_nothing() -> None:
    result = read_pasted(io.StringIO("\n"))
    assert result.ok and result.entries == []
