"""Tests for YouTube URL parsing and link classification."""

from __future__ import annotations

import pytest

from ytripper.urls import (
    Link,
    LinkError,
    LinkKind,
    canonical_channel_url,
    canonical_playlist_url,
    canonical_video_url,
    classify_url,
    parse_video_id,
)

VID = "_hqB_JFI3e8"
PLAYLIST = "PLPPUs8ihmoypPkhnDP3CGkRlsf-o8lje4"
CHANNEL_ID = "UCabcdefghijklmnopqrstuv"


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


# ------------------------------------------------------------ classify_url
@pytest.mark.parametrize(
    "url",
    [
        f"https://youtu.be/{VID}?si=tracking",
        f"https://www.youtube.com/watch?v={VID}",
        f"https://www.youtube.com/watch?v={VID}&list={PLAYLIST}&index=3",  # the video, not the playlist
        f"https://www.youtube.com/shorts/{VID}",
        f"https://www.youtube.com/live/{VID}",
        f"https://www.youtube.com/embed/{VID}",
        f"https://music.youtube.com/watch?v={VID}",
        f"youtu.be/{VID}",  # pasted without https://
        f"www.youtube.com/watch?v={VID}",
    ],
)
def test_classify_video(url: str) -> None:
    assert classify_url(url) == Link(LinkKind.VIDEO, VID, f"https://www.youtube.com/watch?v={VID}")


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/playlist?list={PLAYLIST}",
        f"https://www.youtube.com/playlist?list={PLAYLIST}&si=abc",
        f"https://m.youtube.com/playlist?list={PLAYLIST}",
        f"https://music.youtube.com/playlist?list={PLAYLIST}",
        f"youtube.com/playlist?list={PLAYLIST}",
    ],
)
def test_classify_playlist(url: str) -> None:
    link = classify_url(url)
    assert link == Link(LinkKind.PLAYLIST, PLAYLIST, f"https://www.youtube.com/playlist?list={PLAYLIST}")


@pytest.mark.parametrize(
    ("url", "key", "canonical"),
    [
        ("https://www.youtube.com/@UFIFAS", "@UFIFAS", "https://www.youtube.com/@UFIFAS"),
        ("https://www.youtube.com/@UFIFAS/videos", "@UFIFAS", "https://www.youtube.com/@UFIFAS"),
        ("https://www.youtube.com/@UFIFAS/shorts?si=x", "@UFIFAS", "https://www.youtube.com/@UFIFAS"),
        ("https://m.youtube.com/@uf.plant-medicine_1/streams", "@uf.plant-medicine_1",
         "https://www.youtube.com/@uf.plant-medicine_1"),
        ("youtube.com/@UFIFAS", "@UFIFAS", "https://www.youtube.com/@UFIFAS"),
        (f"https://www.youtube.com/channel/{CHANNEL_ID}", CHANNEL_ID, f"https://www.youtube.com/channel/{CHANNEL_ID}"),
        (f"https://www.youtube.com/channel/{CHANNEL_ID}/playlists", CHANNEL_ID,
         f"https://www.youtube.com/channel/{CHANNEL_ID}"),
        ("https://www.youtube.com/c/UFIFAS", "c/UFIFAS", "https://www.youtube.com/c/UFIFAS"),
        ("https://www.youtube.com/user/ufifas/featured", "user/ufifas", "https://www.youtube.com/user/ufifas"),
    ],
)
def test_classify_channel(url: str, key: str, canonical: str) -> None:
    assert classify_url(url) == Link(LinkKind.CHANNEL, key, canonical)


def test_classify_channel_non_ascii_handle_is_percent_encoded_in_url() -> None:
    link = classify_url("https://www.youtube.com/@%E3%81%BF%E3%81%A9%E3%82%8A")  # @みどり
    assert link.kind is LinkKind.CHANNEL and link.key == "@みどり"
    assert link.url == "https://www.youtube.com/@%E3%81%BF%E3%81%A9%E3%82%8A"


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("", "empty"),
        ("   ", "empty"),
        ("hello world", "not a web link"),
        ("ftp://youtu.be/_hqB_JFI3e8", "not a web link"),
        ("https://vimeo.com/12345", "not a YouTube link"),
        ("https://youtube.com.evil.example/watch?v=_hqB_JFI3e8", "not a YouTube link"),
        ("https://www.youtube.com/watch?v=tooshort", "video ID"),
        ("https://www.youtube.com/watch", "video ID"),
        ("https://youtu.be/", "video ID"),
        ("https://www.youtube.com/shorts/abc", "video ID"),
        ("https://www.youtube.com/playlist", "playlist ID"),
        ("https://www.youtube.com/playlist?list=bad%20id!", "playlist ID"),
        ("https://www.youtube.com/playlist?list=WL", "sign-in"),
        ("https://www.youtube.com/playlist?list=LL", "sign-in"),
        (f"https://www.youtube.com/playlist?list=RD{VID}", "Mix"),
        ("https://www.youtube.com/@ab", "handle"),
        ("https://www.youtube.com/@bad!handle", "handle"),
        ("https://www.youtube.com/channel/UCshort", "channel ID"),
        ("https://www.youtube.com/channel", "channel ID"),
        ("https://www.youtube.com/c/", "channel name"),
        ("https://www.youtube.com/user", "channel name"),
        ("https://www.youtube.com/ufifas", "unsupported"),
        ("https://www.youtube.com/feed/subscriptions", "unsupported"),
        ("https://www.youtube.com/", "unsupported"),
        ("https://[broken", "not a valid web link"),
    ],
)
def test_classify_rejects_with_reason(url: str, reason: str) -> None:
    with pytest.raises(LinkError, match=reason):
        classify_url(url)


def test_link_error_is_a_value_error() -> None:
    with pytest.raises(ValueError):
        classify_url("https://vimeo.com/1")


def test_canonical_playlist_and_channel_urls_reject_bad_keys() -> None:
    assert canonical_playlist_url(PLAYLIST).endswith(PLAYLIST)
    for bad in ("", "a b", "x" * 65):
        with pytest.raises(ValueError):
            canonical_playlist_url(bad)
    for bad in ("", "@a", "UCshort", "x/name", "c/", "c/a b"):
        with pytest.raises(ValueError):
            canonical_channel_url(bad)
