"""Tests for finding the videos behind channel, playlist and video links.

yt-dlp is replaced by a fake listing reader so these tests never touch the network.
"""

from __future__ import annotations

from typing import Any

import pytest

from ytripper import discovery
from ytripper.discovery import (
    SKIP_NOT_YET_AVAILABLE,
    SKIP_REQUIRES_SIGN_IN,
    SKIP_UNAVAILABLE,
    ListingFailed,
    Source,
    SourceKind,
    build_listing_options,
    classify_listing_error,
    discover,
    skip_reason_for,
)
from ytripper.urls import Link, LinkKind, canonical_channel_url, canonical_playlist_url, canonical_video_url

CHANNEL = Link(LinkKind.CHANNEL, "@UFIFAS", canonical_channel_url("@UFIFAS"))
PLAYLIST_ID = "PLPPUs8ihmoypPkhnDP3CGkRlsf-o8lje4"
PLAYLIST = Link(LinkKind.PLAYLIST, PLAYLIST_ID, canonical_playlist_url(PLAYLIST_ID))
OTHER_PLAYLIST_ID = "PLzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"
OTHER_PLAYLIST = Link(LinkKind.PLAYLIST, OTHER_PLAYLIST_ID, canonical_playlist_url(OTHER_PLAYLIST_ID))

V1, V2, V3, V4, V5, V6 = "aaaaaaaaaa1", "aaaaaaaaaa2", "aaaaaaaaaa3", "aaaaaaaaaa4", "aaaaaaaaaa5", "aaaaaaaaaa6"


def video_link(video_id: str) -> Link:
    return Link(LinkKind.VIDEO, video_id, canonical_video_url(video_id))


def entry(video_id: str, **extra: Any) -> dict[str, Any]:
    return {"_type": "url", "ie_key": "Youtube", "id": video_id, "title": f"Title {video_id}",
            "url": canonical_video_url(video_id), **extra}


def tab(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"_type": "playlist", "channel": "UF/IFAS", "channel_id": "UCabcdefghijklmnopqrstuv",
            "entries": list(entries)}


class FakeExtract:
    """Maps listing URLs to info dicts or exceptions and records every call."""

    def __init__(self, pages: dict[str, Any]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def __call__(self, url: str) -> dict[str, Any] | None:
        self.calls.append(url)
        page = self.pages.get(url, ListingFailed(f"no fake page for {url}"))
        if isinstance(page, Exception):
            raise page
        return page


def channel_pages(videos=(), shorts=(), streams=()) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    base = CHANNEL.url
    return {
        f"{base}/videos": tab(*videos) if videos is not None else ListingFailed("This channel does not have a videos tab"),
        f"{base}/shorts": tab(*shorts) if shorts is not None else ListingFailed("This channel does not have a shorts tab"),
        f"{base}/streams": tab(*streams) if streams is not None else ListingFailed("This channel does not have a streams tab"),
    }


# ------------------------------------------------------------------ channels
def test_channel_reads_videos_shorts_and_past_streams() -> None:  # F1, F1a
    fake = FakeExtract(channel_pages(videos=[entry(V1)], shorts=[entry(V2)],
                                     streams=[entry(V3, live_status="was_live")]))
    result = discover([CHANNEL], fake)
    assert fake.calls == [f"{CHANNEL.url}/videos", f"{CHANNEL.url}/shorts", f"{CHANNEL.url}/streams"]
    assert [v.video_id for v in result.queued] == [V1, V2, V3]
    assert [v.found_via[0].tab for v in result.videos.values()] == ["videos", "shorts", "streams"]
    assert result.errors == [] and not result.blocked


def test_channel_without_a_tab_is_not_an_error() -> None:
    fake = FakeExtract(channel_pages(videos=[entry(V1)], shorts=None, streams=None))
    result = discover([CHANNEL], fake)
    assert list(result.videos) == [V1] and result.errors == []


def test_channel_fills_channel_name_and_id_from_the_tab() -> None:
    result = discover([CHANNEL], FakeExtract(channel_pages(videos=[entry(V1)])))
    video = result.videos[V1]
    assert (video.channel, video.channel_id) == ("UF/IFAS", "UCabcdefghijklmnopqrstuv")
    assert str(video.found_via[0]) == "channel UF/IFAS (Videos)"


def test_upcoming_and_live_streams_are_skipped_as_not_yet_available() -> None:  # F1b
    fake = FakeExtract(channel_pages(streams=[entry(V1, live_status="is_upcoming"), entry(V2, live_status="is_live"),
                                              entry(V3, live_status="was_live"), entry(V4, live_status="post_live")]))
    result = discover([CHANNEL], fake)
    assert result.videos[V1].status_text == f"skipped: {SKIP_NOT_YET_AVAILABLE}"
    assert result.videos[V2].skip_reason == SKIP_NOT_YET_AVAILABLE
    assert result.videos[V3].queued and result.videos[V4].queued


def test_members_only_and_paid_videos_are_skipped_and_the_run_continues() -> None:  # F1c
    fake = FakeExtract(channel_pages(videos=[entry(V1, availability="subscriber_only"),
                                             entry(V2, availability="premium_only"),
                                             entry(V3, availability="needs_auth"),
                                             entry(V4, availability="public")]))
    result = discover([CHANNEL], fake)
    assert [v.skip_reason for v in result.videos.values()] == [SKIP_REQUIRES_SIGN_IN] * 3 + [None]
    assert result.videos[V1].status_text == "skipped: requires sign-in"
    assert [v.video_id for v in result.queued] == [V4]


def test_channel_that_cannot_be_read_gives_one_error_and_stops_that_channel() -> None:
    fake = FakeExtract({f"{CHANNEL.url}/videos": ListingFailed("HTTP Error 404: Not Found")})
    result = discover([CHANNEL, video_link(V5)], fake)
    assert fake.calls == [f"{CHANNEL.url}/videos"]
    assert len(result.errors) == 1 and "Videos tab: HTTP Error 404" in result.errors[0].reason
    assert list(result.videos) == [V5]  # the next link is still processed


def test_a_later_tab_error_is_recorded_and_other_tabs_still_read() -> None:
    pages = channel_pages(videos=[entry(V1)], streams=[entry(V3)])
    pages[f"{CHANNEL.url}/shorts"] = ListingFailed("Unable to download API page: timed out")
    result = discover([CHANNEL], FakeExtract(pages))
    assert list(result.videos) == [V1, V3]
    assert [e.reason for e in result.errors] == ["Shorts tab: Unable to download API page: timed out"]


# ----------------------------------------------------------------- playlists
def test_playlist_includes_unlisted_and_skips_private_or_deleted() -> None:  # F3
    page = {"_type": "playlist", "id": PLAYLIST_ID, "title": "Seminars", "entries": [
        entry(V1, availability="unlisted"),
        entry(V2),
        entry(V3, title="[Private video]"),
        entry(V4, title="[Deleted video]"),
        entry(V5, availability="private"),
    ]}
    result = discover([PLAYLIST], FakeExtract({PLAYLIST.url: page}))
    assert [v.video_id for v in result.queued] == [V1, V2]
    assert {v.video_id for v in result.skipped} == {V3, V4, V5}
    assert all(v.skip_reason == SKIP_UNAVAILABLE for v in result.skipped)
    assert str(result.videos[V1].found_via[0]) == f"playlist 'Seminars' ({PLAYLIST_ID})"


def test_playlist_error_is_recorded_and_other_links_continue() -> None:
    fake = FakeExtract({PLAYLIST.url: ListingFailed("The playlist does not exist")})
    result = discover([PLAYLIST, video_link(V1)], fake)
    assert [str(e) for e in result.errors] == [f"{PLAYLIST.url}: The playlist does not exist"]
    assert list(result.videos) == [V1]


def test_non_video_and_malformed_entries_are_ignored() -> None:
    page = {"_type": "playlist", "title": "Mixed", "entries": [
        entry(V1),
        {"_type": "url", "ie_key": "YoutubeTab", "id": "PLnested", "url": "https://www.youtube.com/playlist?list=x"},
        {"_type": "url", "ie_key": "Youtube", "id": "bad id; rm"},
        None,
        "not a dict",
    ]}
    result = discover([PLAYLIST], FakeExtract({PLAYLIST.url: page}))
    assert list(result.videos) == [V1]


def test_empty_listing() -> None:
    result = discover([PLAYLIST], FakeExtract({PLAYLIST.url: {"_type": "playlist", "entries": []}}))
    assert result.videos == {} and result.errors == []


# ------------------------------------------------------- video links, F4a
def test_video_link_needs_no_network() -> None:  # F2
    fake = FakeExtract({})
    result = discover([video_link(V1)], fake)
    assert fake.calls == []
    video = result.videos[V1]
    assert video.url == canonical_video_url(V1) and video.queued
    assert video.found_via == [Source(SourceKind.LINK, V1)] and str(video.found_via[0]) == "video link"


def test_video_found_through_several_links_is_listed_once_with_every_source() -> None:  # F4a
    pages = channel_pages(videos=[entry(V1), entry(V2)])
    pages[PLAYLIST.url] = {"_type": "playlist", "title": "Seminars",
                           "entries": [entry(V2, duration=61, upload_date="20240501"), entry(V3)]}
    result = discover([CHANNEL, PLAYLIST, video_link(V2), video_link(V3)], FakeExtract(pages))
    assert list(result.videos) == [V1, V2, V3]
    v2 = result.videos[V2]
    assert [s.kind for s in v2.found_via] == [SourceKind.CHANNEL, SourceKind.PLAYLIST, SourceKind.LINK]
    assert (v2.duration_s, v2.upload_date) == (61.0, "20240501")  # filled in from the playlist entry


def test_skip_reason_from_any_source_wins() -> None:
    pages = {PLAYLIST.url: {"entries": [entry(V1)]},
             OTHER_PLAYLIST.url: {"entries": [entry(V1, availability="subscriber_only")]}}
    result = discover([PLAYLIST, OTHER_PLAYLIST], FakeExtract(pages))
    assert result.videos[V1].skip_reason == SKIP_REQUIRES_SIGN_IN


def test_same_link_twice_is_read_once() -> None:
    fake = FakeExtract({PLAYLIST.url: {"entries": [entry(V1)]}})
    discover([PLAYLIST, PLAYLIST], fake)
    assert fake.calls == [PLAYLIST.url]


def test_upload_date_from_timestamp() -> None:
    page = {"entries": [entry(V1, timestamp=1714521600)]}  # 2024-05-01T00:00:00Z
    assert discover([PLAYLIST], FakeExtract({PLAYLIST.url: page})).videos[V1].upload_date == "20240501"


# -------------------------------------------------------------- bot check
def test_bot_check_stops_discovery_and_marks_result_blocked() -> None:  # NF11b
    bot = ListingFailed("Sign in to confirm you're not a bot. Use --cookies-from-browser")
    fake = FakeExtract({PLAYLIST.url: bot, OTHER_PLAYLIST.url: {"entries": [entry(V2)]}})
    result = discover([video_link(V1), PLAYLIST, OTHER_PLAYLIST], fake)
    assert result.blocked
    assert fake.calls == [PLAYLIST.url]  # nothing after the block is read
    assert list(result.videos) == [V1] and len(result.errors) == 1


def test_bot_check_on_a_channel_tab_also_stops() -> None:
    pages = channel_pages(videos=[entry(V1)])
    pages[f"{CHANNEL.url}/shorts"] = ListingFailed("Sign in to confirm you\u2019re not a bot")
    fake = FakeExtract(pages)
    result = discover([CHANNEL], fake)
    assert result.blocked and f"{CHANNEL.url}/streams" not in fake.calls


# ------------------------------------------------------------ helpers
@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("This channel does not have a shorts tab", "missing_tab"),
        ("Sign in to confirm you're not a bot", "bot_check"),
        ("Sign in to confirm you\u2019re not a bot", "bot_check"),
        ("HTTP Error 429: Too Many Requests", "rate_limited"),
        ("HTTP Error 404: Not Found", "listing_error"),
    ],
)
def test_classify_listing_error(message: str, code: str) -> None:
    assert classify_listing_error(message) == code
    assert ListingFailed(message).code == code


def test_skip_reason_for_plain_public_video_is_none() -> None:
    assert skip_reason_for({"id": V1, "title": "Talk", "availability": "public", "live_status": "not_live"}) is None


def test_listing_options_are_flat_and_never_authenticate() -> None:  # NF4
    opts = build_listing_options()
    assert opts["extract_flat"] == "in_playlist" and opts["skip_download"] is True
    for forbidden in ("cookiefile", "cookiesfrombrowser", "username", "password", "usenetrc"):
        assert forbidden not in opts


def test_default_extractor_wraps_ytdlp_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    yt_dlp = pytest.importorskip("yt_dlp")
    from yt_dlp.utils import DownloadError

    class FailingYDL:
        def __init__(self, opts: dict[str, Any]) -> None:
            assert opts["extract_flat"] == "in_playlist"

        def __enter__(self) -> "FailingYDL":
            return self

        def __exit__(self, *exc: Any) -> None:
            return None

        def extract_info(self, url: str, download: bool) -> dict[str, Any]:
            assert download is False
            raise DownloadError("ERROR: Sign in to confirm you're not a bot")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FailingYDL)
    with pytest.raises(ListingFailed, match="^Sign in to confirm") as caught:
        discovery._ytdlp_extract(PLAYLIST.url)
    assert caught.value.code == "bot_check"
