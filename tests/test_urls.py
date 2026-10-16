"""Tests for single-video URL parsing."""

from __future__ import annotations

import pytest

from ytripper.urls import canonical_video_url, parse_video_id


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://youtu.be/_hqB_JFI3e8?si=pUy8WJX22C000KWM", "_hqB_JFI3e8"),
        ("https://www.youtube.com/watch?v=_hqB_JFI3e8&list=PLx", "_hqB_JFI3e8"),
        ("https://m.youtube.com/watch?v=_hqB_JFI3e8", "_hqB_JFI3e8"),
        ("https://www.youtube.com/shorts/_hqB_JFI3e8", "_hqB_JFI3e8"),
        ("https://www.youtube.com/live/_hqB_JFI3e8?feature=share", "_hqB_JFI3e8"),
        ("  https://youtu.be/_hqB_JFI3e8  ", "_hqB_JFI3e8"),
        ("https://www.youtube.com/watch?v=tooshort", None),
        ("https://evil.example.com/watch?v=_hqB_JFI3e8", None),
        ("ftp://youtu.be/_hqB_JFI3e8", None),
        ("https://www.youtube.com/playlist?list=PLPPUs8ihmoypPkhnDP3CGkRlsf-o8lje4", None),
        ("not a url", None),
        ("", None),
    ],
)
def test_parse_video_id(url: str, expected: str | None) -> None:
    assert parse_video_id(url) == expected


def test_canonical_url() -> None:
    assert canonical_video_url("_hqB_JFI3e8") == "https://www.youtube.com/watch?v=_hqB_JFI3e8"


def test_canonical_url_rejects_bad_id() -> None:
    with pytest.raises(ValueError):
        canonical_video_url("bad id; rm -rf")
