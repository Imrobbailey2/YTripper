"""Tests for description parsing (F19) against synthetic and real sample descriptions."""

from __future__ import annotations

from pathlib import Path

import pytest

from ytripper.description import (
    apply_to_info,
    build_record,
    parse_description,
    parse_timestamp,
    split_names,
    split_sentences,
    summary,
    to_ytdlp_chapters,
)
from ytripper.paths import PROJECT_ROOT

SAMPLES = PROJECT_ROOT / "samples" / "descriptions"
CHANNEL = "UF Doctor of Plant Medicine Program"

ALL_TYPES = """Welcome to the talk!
00:00 Intro
1:05 Part one - setup
1:02:03 Wrap up
Author: Dr. Jane Doe
Music: Kevin Example
Filmed by: Sam Cutter
Website: https://example.org/page.
More at https://example.org/page and https://example.org/other
#PlantHealth #fruitflies
"""


def _sample(name: str) -> str:
    return (SAMPLES / name).read_text(encoding="utf-8")


# ------------------------------------------------------------- acceptance
def test_all_types_acceptance() -> None:
    d = parse_description(ALL_TYPES, title="Talk", channel="Chan")
    assert [c["start"] for c in d["chapters"]] == [0, 65, 3723]
    assert [c["title"] for c in d["chapters"]] == ["Intro", "Part one - setup", "Wrap up"]
    assert d["hashtags"] == ["#PlantHealth", "#fruitflies"]
    assert [(c["role"], c["name"]) for c in d["credits"]] == [("Music", "Kevin Example"), ("Filmed by", "Sam Cutter")]
    assert (d["author"], d["author_source"]) == ("Jane Doe", "description_label")
    assert [link["url"] for link in d["links"]] == ["https://example.org/page", "https://example.org/other"]
    assert d["links"][0]["label"] == "Website"


def test_empty_description_falls_back_to_channel() -> None:
    d = parse_description("", title="Plain title", channel="Chan")
    assert d == {"author": "Chan", "author_source": "channel", "chapters": [], "hashtags": [],
                 "credits": [], "links": []}


def test_none_and_no_channel() -> None:
    d = parse_description(None, title="", channel="")  # type: ignore[arg-type]
    assert d["author_source"] == "none" and d["author"] == ""


# ------------------------------------------------------------- real samples
@pytest.mark.parametrize(
    ("sample", "title", "author", "source"),
    [
        ("tephritidae_norrbom.txt", "Identification of Tephritidae", "Allen Norrbom", "description_bio"),
        ("carpomyini_steck.txt", "Carpomyini larvae", "Gary Steck", "description_bio"),
        ("dacus_leblanc.txt", "Dacus", "Luc Leblanc", "description_bio"),
        ("tephritidae_norrbom.txt", "Overview of Tephritidae Molecular Phylogeny – Camiel Doorenweerd",
         "Camiel Doorenweerd", "title"),
    ],
)
def test_real_sample_author(sample: str, title: str, author: str, source: str) -> None:
    d = parse_description(_sample(sample), title=title, channel=CHANNEL)
    assert (d["author"], d["author_source"]) == (author, source)


@pytest.mark.parametrize("sample", ["tephritidae_norrbom.txt", "carpomyini_steck.txt", "dacus_leblanc.txt"])
def test_real_sample_credits(sample: str) -> None:
    d = parse_description(_sample(sample), title="x", channel=CHANNEL)
    credits = [(c["role"], c["name"], c["note"]) for c in d["credits"]]
    assert credits[:5] == [("Lectures", f"Dr. {n}", None) for n in
                           ("Norman Barr", "Camiel Doorenweerd", "Luc Leblanc", "Allen Norrbom", "Gary Steck")]
    assert ("Project coordination", "Dr. Amanda Hodges", "DPM Director, University of Florida") in credits
    assert ("In association with", "University of Florida BRE lab", None) in credits
    assert ("In association with", "Platinum Digital Video", None) in credits
    hosting = [c for c in d["credits"] if c["role"] == "Hosting and filming"]
    assert len(hosting) == 1 and hosting[0]["name"].startswith("USDA-APHIS Plant Protection Act")
    assert "AP18PPQS&TT00C146" in hosting[0]["name"]
    assert len(d["credits"]) == 9
    assert d["chapters"] == [] and d["hashtags"] == [] and d["links"] == []


# ------------------------------------------------------------- author rules
def test_title_suffix_needs_supporting_evidence() -> None:
    d = parse_description("No names mentioned here.", title="Part 1 - Fruit Flies", channel="Chan")
    assert d["author_source"] == "channel"


def test_title_prefix_name_is_accepted_when_in_description() -> None:
    d = parse_description("Thanks to Jane Doe for this talk.", title="Jane Doe | Soil Health", channel="Chan")
    assert (d["author"], d["author_source"]) == ("Jane Doe", "title")


def test_label_beats_title_and_bio() -> None:
    text = "By: Ana María de la Cruz\nDr. Gary Steck is an entomologist."
    d = parse_description(text, title="Talk – Gary Steck", channel="Chan")
    assert (d["author"], d["author_source"]) == ("Ana María de la Cruz", "description_label")


@pytest.mark.parametrize("line", ["This is part of a series.", "Lectures were provided by many people.",
                                  "Primary species is covered.", "It has been updated."])
def test_bio_rule_ignores_non_names(line: str) -> None:
    assert parse_description(line, title="t", channel="Chan")["author_source"] == "channel"


# ------------------------------------------------------------- chapters
def test_trailing_timestamps_and_brackets() -> None:
    d = parse_description("Intro - 0:00\n[2:30] Methods\nResults (10:00)", title="t", channel="c")
    assert [(c["start"], c["title"]) for c in d["chapters"]] == [(0, "Intro"), (150, "Methods"), (600, "Results")]


def test_url_with_time_is_not_a_chapter() -> None:
    assert parse_description("https://youtu.be/abc?t=1:30", title="t", channel="c")["chapters"] == []


def test_parse_timestamp() -> None:
    assert parse_timestamp("1:02:03") == 3723 and parse_timestamp("05:07") == 307


def test_to_ytdlp_chapters() -> None:
    chapters = [{"start": 0, "title": "A"}, {"start": 60, "title": "B"}]
    assert to_ytdlp_chapters(chapters, 120) == [
        {"start_time": 0.0, "end_time": 60.0, "title": "A"},
        {"start_time": 60.0, "end_time": 120.0, "title": "B"},
    ]
    assert to_ytdlp_chapters(chapters[:1], 120) == []
    assert to_ytdlp_chapters([{"start": 60, "title": "B"}, {"start": 0, "title": "A"}], 120) == []
    assert to_ytdlp_chapters(chapters, 30) == []


# ------------------------------------------------------------- hashtags / links
def test_hashtags_ignore_urls_numbers_and_entities() -> None:
    text = "#Fruit #fruit #2024 &#39; https://x.com/#frag mid#word #Ñandú"
    assert parse_description(text, title="t", channel="c")["hashtags"] == ["#Fruit", "#Ñandú"]


def test_links_trailing_punctuation_parentheses_and_www() -> None:
    text = "(see https://en.wikipedia.org/wiki/Fly_(insect)).\nSite:\nwww.example.com,"
    links = parse_description(text, title="t", channel="c")["links"]
    assert links == [
        {"url": "https://en.wikipedia.org/wiki/Fly_(insect)", "label": "(see"},
        {"url": "https://www.example.com", "label": "Site"},
    ]


# ------------------------------------------------------------- helpers
def test_split_sentences_respects_abbreviations() -> None:
    text = "Lectures by Dr. Norman Barr and D. ciliatus. Next sentence. No. 5 is here."
    assert split_sentences(text) == ["Lectures by Dr. Norman Barr and D. ciliatus.", "Next sentence.", "No. 5 is here."]


def test_split_names_keeps_parenthetical_notes() -> None:
    assert split_names("Dr. A (Director, UF), B and the C lab") == [
        ("Dr. A", "Director, UF"), ("B", None), ("C lab", None)]


# ------------------------------------------------------------- yt-dlp bridging
def test_apply_to_info_prefers_youtube_chapters() -> None:
    info = {"chapters": [{"start_time": 0, "end_time": 5, "title": "YT"}], "duration": 5}
    details = parse_description("0:00 A\n0:02 B", title="t", channel="c")
    assert apply_to_info(info, details) == "youtube"
    assert info["chapters"][0]["title"] == "YT"
    assert info["artist"] == "c" and info["artists"] == ["c"]


def test_apply_to_info_falls_back_to_description() -> None:
    info = {"duration": 100}
    details = parse_description("0:00 A\n0:50 B", title="t", channel="c")
    assert apply_to_info(info, details) == "description"
    assert [c["title"] for c in info["chapters"]] == ["A", "B"]


def test_apply_to_info_none() -> None:
    info: dict = {"duration": 100}
    assert apply_to_info(info, parse_description("", title="t", channel="")) == "none"
    assert "artist" not in info and "chapters" not in info


def test_build_record_and_summary() -> None:
    info = {"id": "_hqB_JFI3e8", "title": "T", "upload_date": "20201214", "channel": CHANNEL,
            "chapters": [{"start_time": 0, "end_time": 9, "title": "Intro"}]}
    details = parse_description(ALL_TYPES, title="T", channel=CHANNEL)
    record = build_record(info, details, "youtube")
    assert record["upload_date"] == "2020-12-14"
    assert record["youtube_chapters"] == [{"start": 0, "end": 9, "title": "Intro"}]
    assert record["author"] == "Jane Doe" and record["playlists"] == []
    assert summary(details) == {"author": "Jane Doe", "author_source": "description_label", "chapter_count": 3,
                                "hashtag_count": 2, "link_count": 2, "credit_count": 2}
