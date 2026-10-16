"""Structured details from a video description (F19).

Pure functions only - no network, no yt-dlp import - so every rule is unit
tested against sample descriptions in ``samples/descriptions``.

Extracted fields:
    chapters  - timestamp lines ("00:00 Intro", "Intro - 1:02:03")
    hashtags  - "#tag" words (URLs excluded), de-duplicated case-insensitively
    credits   - "Role: Name" lines and prose such as
                "Lectures were provided by A, B, and C" /
                "... in association with X and Y" /
                "Hosting and filming ... is possible through Z"
    author    - first of: labelled line ("Author: ...") -> name suffix in the
                title confirmed by the description -> biography sentence
                ("Dr. Gary Steck is ...") -> channel name
    links     - http(s)/www URLs with the text of their line as a label
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

# --------------------------------------------------------------------- regexes
_TS = r"(?:\d{1,2}:)?\d{1,2}:\d{2}"
_TS_LEADING_RE = re.compile(rf"^\s*[\[(]?(?P<ts>{_TS})[\])]?\s*(?:[-–—:|.)•]\s*)?(?P<title>\S.*?)\s*$")
_TS_TRAILING_RE = re.compile(rf"^\s*(?P<title>\S.*?)\s*(?:[-–—:|•]\s*)?[\[(]?(?P<ts>{_TS})[\])]?\s*$")

_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"'`]+", re.IGNORECASE)
_URL_TRAILING = ".,;:!?'\"”’"
_HASHTAG_RE = re.compile(r"(?<![\w#&/])#(?P<tag>\w*[^\W\d_]\w*)", re.UNICODE)

_ROLE_WORDS = (
    r"music|songs?|soundtrack|audio|sound(?:\s+design)?|edit(?:ed|ing|or|ors)?|filmed|filming|camera|"
    r"cinematography|videograph(?:y|er|ers)|video(?:\s+production)?|produc(?:ed|er|ers|tion)|"
    r"direct(?:ed|or|ion)|host(?:ed|s)?|presenters?|presented|speakers?|lecturers?|instructors?|"
    r"narrat(?:or|ed|ion)|moderat(?:or|ed)|thumbnail|graphics|animation|script|writers?|"
    r"coordinat(?:ion|or|ed)|funding|funded|sponsors?|sponsored|special\s+thanks|thanks"
)
_LABEL_CREDIT_RE = re.compile(
    rf"^\s*(?P<role>(?:[A-Za-z][\w&'/-]*\s+){{0,3}}?(?:{_ROLE_WORDS})(?:\s+by)?)\s*:\s*(?P<names>\S.*?)\s*$",
    re.IGNORECASE,
)
_AUTHOR_LABEL_RE = re.compile(
    r"^\s*(?:author|written\s+by|created\s+by|presented\s+by|presenter|speaker|lecturer|by)\s*:\s*(?P<name>\S.*?)\s*$",
    re.IGNORECASE,
)
_PROVIDED_BY_RE = re.compile(
    r"^(?P<role>[A-Z][\w ,&/'-]{2,60}?)\s+(?:was|were|is|are|has\s+been|have\s+been)\s+(?:kindly\s+)?"
    r"(?:provided|given|delivered|presented|produced|filmed|edited|recorded|coordinated|hosted|"
    r"sponsored|funded|supported)\s+by\s+(?P<names>.+?)\.?$"
)
_POSSIBLE_THROUGH_RE = re.compile(
    r"^(?P<role>[A-Z].{2,120}?)\s+(?:is|was|are|were)\s+(?:made\s+)?possible\s+(?:through|by|thanks\s+to)\s+(?P<names>.+?)\.?$"
)
_ASSOCIATION_RE = re.compile(r"\s+in\s+(?:association|collaboration|partnership)\s+with\s+", re.IGNORECASE)

_HONORIFIC_RE = re.compile(r"^(?:Dr|Prof|Professor|Mr|Mrs|Ms|Mx)\.?\s+", re.IGNORECASE)
_NAME_SUFFIX_RE = re.compile(r",?\s+(?:Ph\.?\s?D\.?|M\.?D\.?|Jr\.?|Sr\.?|MSc|M\.?S\.?)$", re.IGNORECASE)
_BIO_RE = re.compile(
    r"^(?P<hon>(?:Dr|Prof|Professor|Mr|Mrs|Ms)\.?\s+)?"
    r"(?P<name>[^\W\d_][\w'’-]*(?:\s+(?:[^\W\d_][\w'’.-]*))*?)\s+"
    r"(?:is|has|was|serves|works|holds|joined|received|earned|completed|leads|specializes|specialises)\b"
)
_TITLE_SEP_RE = re.compile(r"\s+[–—|-]\s+|\s*\|\s*")

_ABBREVIATIONS = {
    "dr", "mr", "mrs", "ms", "mx", "prof", "sr", "jr", "st", "no", "nos", "vs", "etc", "e.g", "i.e",
    "inc", "ltd", "co", "corp", "dept", "univ", "approx", "fig", "vol", "pp", "ca", "al",
}
_NAME_PARTICLES = {"de", "da", "del", "della", "der", "den", "di", "du", "la", "le", "van", "von", "y", "bin", "al"}
_NOT_NAMES = {
    "this", "these", "that", "those", "it", "he", "she", "they", "we", "our", "the", "there", "here",
    "each", "every", "your", "my", "currently", "subsequently", "since", "after", "today", "now",
}


# -------------------------------------------------------------------- helpers
def parse_timestamp(text: str) -> int:
    """Convert ``h:mm:ss`` / ``m:ss`` to seconds."""
    seconds = 0
    for part in text.split(":"):
        seconds = seconds * 60 + int(part)
    return seconds


def split_sentences(line: str) -> list[str]:
    """Split one line into sentences without breaking on "Dr.", "No.", initials, etc."""
    sentences: list[str] = []
    start = 0
    for match in re.finditer(r"[.!?](?=\s+[\"“(]?[A-Z0-9])", line):
        end = match.end()
        word = re.search(r"([\w.]+)\.$", line[start:end])
        token = word.group(1).lower() if word else ""
        if token in _ABBREVIATIONS or (len(token) == 1 and token.isalpha()):
            continue
        sentences.append(line[start:end].strip())
        start = end
    tail = line[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def _strip_url(url: str) -> str:
    url = url.rstrip(_URL_TRAILING)
    while url.endswith(")") and url.count("(") < url.count(")"):
        url = url[:-1].rstrip(_URL_TRAILING)
    return url


def split_names(text: str) -> list[tuple[str, str | None]]:
    """Split "A, B (note, x), and C" into [(name, note)], respecting parentheses."""
    protected, depth = [], 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        protected.append("\x00" if ch == "," and depth else ch)
    joined = "".join(protected)
    joined = re.sub(r"\(([^)]*)\)", lambda m: "(" + m.group(1).replace(" and ", " \x01 ") + ")", joined)
    parts = re.split(r"\s*,\s*(?:and\s+|&\s+)?|\s*;\s*|\s+(?:and|&)\s+", joined)
    result: list[tuple[str, str | None]] = []
    for raw in parts:
        part = raw.replace("\x00", ",").replace(" \x01 ", " and ").strip().rstrip(".").strip()
        if not part:
            continue
        note = None
        m = re.match(r"^(?P<name>.*?)\s*\((?P<note>[^)]*)\)\s*$", part)
        if m:
            part, note = m.group("name").strip(), m.group("note").strip() or None
        part = re.sub(r"^the\s+", "", part)
        if part and len(part) <= 120:
            result.append((part, note))
    return result


def strip_honorific(name: str) -> str:
    return _NAME_SUFFIX_RE.sub("", _HONORIFIC_RE.sub("", name.strip())).strip()


def looks_like_person(name: str) -> bool:
    """Heuristic: 2-5 capitalised words (particles allowed), no digits."""
    words = strip_honorific(name).split()
    if not 2 <= len(words) <= 5:
        return False
    if words[0].lower() in _NOT_NAMES:
        return False
    for word in words:
        if word.lower() in _NAME_PARTICLES:
            continue
        if not word[0].isupper() or not all(ch.isalpha() or ch in "'’.-" for ch in word):
            return False
    return True


# ----------------------------------------------------------------- extractors
def extract_chapters(text: str) -> list[dict[str, Any]]:
    chapters: list[dict[str, Any]] = []
    seen: set[int] = set()
    for line in text.splitlines():
        if _URL_RE.search(line):
            line = _URL_RE.sub("", line)
        m = _TS_LEADING_RE.match(line) or _TS_TRAILING_RE.match(line)
        if not m:
            continue
        start = parse_timestamp(m.group("ts"))
        title = m.group("title").strip(" -–—:|•")
        if not title or start in seen:
            continue
        seen.add(start)
        chapters.append({"start": start, "start_text": m.group("ts"), "title": title})
    return chapters


def extract_hashtags(text: str) -> list[str]:
    without_urls = _URL_RE.sub(" ", text)
    tags: list[str] = []
    seen: set[str] = set()
    for m in _HASHTAG_RE.finditer(without_urls):
        tag = "#" + m.group("tag")
        if tag.casefold() not in seen:
            seen.add(tag.casefold())
            tags.append(tag)
    return tags


def extract_links(text: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    previous = ""
    for line in text.splitlines():
        found = list(_URL_RE.finditer(line))
        line_label = ""
        cursor = 0
        for m in found:
            # Label = the text between the previous URL (or line start) and this URL.
            segment = " ".join(line[cursor:m.start()].split())
            segment = re.sub(r"^(?:and|or|&|,)(?:\s+|$)|\s+(?:and|or|&)$", "", segment).strip(" \t-–—:|•→>»*,")
            cursor = m.end()
            if not found.index(m) and not segment:
                segment = " ".join(_URL_RE.sub(" ", line).split()).strip(" \t-–—:|•→>»*,")
            label = segment or line_label
            if not label and previous and len(previous) <= 60:
                label = previous.rstrip(":").strip()
            line_label = line_label or label

            url = _strip_url(m.group(0))
            if url.lower().startswith("www."):
                url = "https://" + url
            key = url.rstrip("/").lower()
            if key in seen:
                continue
            seen.add(key)
            links.append({"url": url, "label": label})
        stripped = line.strip()
        if stripped and not found:
            previous = stripped
        elif not stripped:
            previous = ""
    return links


def extract_credits(text: str) -> list[dict[str, Any]]:
    credits: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(role: str, name: str, note: str | None, raw: str) -> None:
        role, name = role.strip().rstrip(":"), name.strip()
        key = (role.casefold(), name.casefold())
        if name and key not in seen:
            seen.add(key)
            credits.append({"role": role, "name": name, "note": note, "raw": raw.strip()})

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or _AUTHOR_LABEL_RE.match(stripped):
            continue
        label = _LABEL_CREDIT_RE.match(stripped)
        if label:
            role = label.group("role").strip()
            role = role[0].upper() + role[1:]
            for name, note in split_names(label.group("names")):
                add(role, name, note, stripped)
            continue
        for sentence in split_sentences(stripped):
            through = _POSSIBLE_THROUGH_RE.match(sentence)
            if through:
                role = re.split(r"\s+of\s+", through.group("role"), maxsplit=1)[0]
                # Funding statements contain commas that are not name separators: keep whole.
                add(role, re.sub(r"^the\s+", "", through.group("names").strip()), None, sentence)
                continue
            provided = _PROVIDED_BY_RE.match(sentence)
            if not provided:
                continue
            names_text = provided.group("names")
            assoc = None
            pieces = _ASSOCIATION_RE.split(names_text, maxsplit=1)
            if len(pieces) == 2:
                names_text, assoc = pieces
            role = provided.group("role").strip()
            for name, note in split_names(names_text):
                add(role, name, note, sentence)
            if assoc:
                for name, note in split_names(assoc):
                    add("In association with", name, note, sentence)
    return credits


def _resolve_full_name(candidate: str, credits: list[dict[str, Any]]) -> str:
    """Expand a surname-only candidate ("Leblanc") using a credited full name."""
    cand_words = strip_honorific(candidate).split()
    if not cand_words:
        return candidate
    for credit in credits:
        full = strip_honorific(credit["name"])
        words = full.split()
        if len(words) > len(cand_words) and words[-1].casefold() == cand_words[-1].casefold():
            return full
    return strip_honorific(candidate)


def determine_author(text: str, title: str, channel: str, credits: list[dict[str, Any]]) -> tuple[str, str]:
    """Return (author, source). Source: description_label | title | description_bio | channel | none."""
    for line in text.splitlines():
        m = _AUTHOR_LABEL_RE.match(line)
        if m:
            return strip_honorific(m.group("name")), "description_label"

    folded = text.casefold()
    segments = [s.strip() for s in _TITLE_SEP_RE.split(title or "") if s.strip()]
    if len(segments) >= 2:
        for candidate in (segments[-1], segments[0]):
            if looks_like_person(candidate):
                surname = strip_honorific(candidate).split()[-1].casefold()
                if surname and surname in folded:
                    return strip_honorific(candidate), "title"

    for line in text.splitlines():
        sentences = split_sentences(line.strip())
        if not sentences:
            continue
        m = _BIO_RE.match(sentences[0])
        if not m:
            continue
        name = m.group("name").strip()
        words = name.split()
        if not words or words[0].casefold() in _NOT_NAMES or len(words) > 5:
            continue
        if not all(w[0].isupper() or w.lower() in _NAME_PARTICLES for w in words):
            continue
        if not m.group("hon") and len(words) < 2:
            continue
        return _resolve_full_name(name, credits), "description_bio"

    if channel:
        return channel, "channel"
    return "", "none"


def parse_description(text: str, *, title: str = "", channel: str = "") -> dict[str, Any]:
    """Extract all F19 fields from a description. Never raises on odd input."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    credits = extract_credits(text)
    author, author_source = determine_author(text, title or "", channel or "", credits)
    return {
        "author": author,
        "author_source": author_source,
        "chapters": extract_chapters(text),
        "hashtags": extract_hashtags(text),
        "credits": credits,
        "links": extract_links(text),
    }


# ------------------------------------------------------------ yt-dlp bridging
def to_ytdlp_chapters(chapters: list[dict[str, Any]], duration: float | None) -> list[dict[str, Any]]:
    """Convert description chapters to yt-dlp's format, or [] if not a valid set.

    Valid means: at least 2 chapters, strictly increasing start times, and
    (when the duration is known) every start before the end of the video.
    """
    if len(chapters) < 2:
        return []
    starts = [c["start"] for c in chapters]
    if any(b <= a for a, b in zip(starts, starts[1:])):
        return []
    if duration and starts[-1] >= duration:
        return []
    result = []
    for i, chapter in enumerate(chapters):
        end = chapters[i + 1]["start"] if i + 1 < len(chapters) else (duration or chapter["start"])
        result.append({"start_time": float(chapter["start"]), "end_time": float(end), "title": chapter["title"]})
    return result


def apply_to_info(info: dict[str, Any], details: dict[str, Any]) -> str:
    """Prepare yt-dlp's info dict for embedding; return the chapter source.

    Sets the artist tag to the author, and falls back to description chapters
    only when YouTube supplied none (architecture decision 4).
    """
    if details.get("author"):
        info["artist"] = details["author"]
        info["artists"] = [details["author"]]
    if info.get("chapters"):
        return "youtube"
    fallback = to_ytdlp_chapters(details.get("chapters") or [], info.get("duration"))
    if fallback:
        info["chapters"] = fallback
        return "description"
    return "none"


def _iso_date(upload_date: str | None) -> str | None:
    if upload_date and re.fullmatch(r"\d{8}", upload_date):
        return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
    return upload_date


def build_record(info: dict[str, Any], details: dict[str, Any], chapters_source: str) -> dict[str, Any]:
    """The ``<id>.details.json`` document for one video."""
    return {
        "id": info.get("id"),
        "title": info.get("title"),
        "upload_date": _iso_date(info.get("upload_date")),
        "channel": info.get("channel") or info.get("uploader"),
        "channel_id": info.get("channel_id"),
        "channel_url": info.get("channel_url"),
        "duration_s": info.get("duration"),
        "webpage_url": info.get("webpage_url"),
        "author": details.get("author"),
        "author_source": details.get("author_source"),
        "chapters": details.get("chapters", []),
        "embedded_chapters_source": chapters_source,
        "youtube_chapters": [
            {"start": c.get("start_time"), "end": c.get("end_time"), "title": c.get("title")}
            for c in (info.get("chapters") or [])
        ] if chapters_source == "youtube" else [],
        "hashtags": details.get("hashtags", []),
        "credits": details.get("credits", []),
        "links": details.get("links", []),
        "playlists": [],
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def summary(details: dict[str, Any]) -> dict[str, Any]:
    """Compact counts stored in the manifest and report."""
    return {
        "author": details.get("author", ""),
        "author_source": details.get("author_source", ""),
        "chapter_count": len(details.get("chapters") or []),
        "hashtag_count": len(details.get("hashtags") or []),
        "link_count": len(details.get("links") or []),
        "credit_count": len(details.get("credits") or []),
    }
