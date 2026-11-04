# YTripper — Build Specification (reconstructed)

**Status:** v1.1, approved 2026-11-02. v1.1 changes: F8 and NF3 returned to their original meanings (the code cites them), so the preview is now F17 and pacing is NF11; decision 4 revised so description chapters are never embedded. Reconstructed from the code at `increment-2-description-details` @ 2792f2b plus user Q&A. The original spec was lost.
**Owner:** Rob Bailey

**Legend**
- ✅ **Confirmed:** you confirmed it in the 2026-11-02 Q&A.
- 🔎 **Recovered:** cited in the code; the original wording is lost.
- 🆕 **New:** written during the rebuild.
- ⚠️ **Proposed:** not yet confirmed.

**Requirement IDs:** IDs the code cites (F5, F6, F7, F8, F9, F10, F11, F19, NF1, NF3, NF4, NF5, NF7, NF10) were kept. F8 and NF3 come from a test comment: "NF3 / F8: nothing re-downloaded". Every other ID was **reassigned** and may not match the original numbering.

---

## 1. Purpose
Make a one-time, **verified**, best-quality backup of a client's YouTube content on Windows. It never signs in, never re-encodes, and can be re-run safely.

## 2. Functional Requirements

### Input and discovery
| ID | Requirement | Priority | Acceptance criteria | Src |
|---|---|---|---|---|
| F1 | Accepts a **channel link** | Must | Given a channel URL, then all of its public videos are queued | ✅ |
| F1a | A channel run includes regular videos, Shorts and past livestream recordings | Must | Given a channel with all three kinds, then all of them are in the preview | ✅ |
| F1b | Upcoming and currently live streams are skipped | Must | They are listed in the report as `skipped: not yet available` | ✅ |
| F1c | Members-only and paid videos are skipped | Must | They are listed as `skipped: requires sign-in`, and the run continues | ✅ |
| F2 | Accepts a **single video link** (youtu.be, watch, shorts, live, embed; `?si=` ignored) | Must | Given any supported form, then exactly that video is queued | ✅ (Increment 1 done) |
| F3 | Accepts a **playlist link**, including unlisted videos in the playlist | Must | Every video in the playlist is queued once | ✅ |
| F4 | Accepts a **list of video links**, either as a **text file path or pasted in** | Must | **File:** UTF-8 (byte-order mark allowed), one link per line, blank lines and `#` comments ignored. **Pasted:** ends at the first blank line. Invalid lines are reported with their line number before the preview. | ✅ |
| F4a | A video found from more than one source is backed up only once | Must | Each video ID appears once in the manifest | ✅ |
| F14 | A channel run also reads every public playlist on the channel to find extra videos (e.g. unlisted videos in a public playlist) | Must | An unlisted video that is only in a public playlist appears in the preview marked as found via that playlist, and is backed up | ✅ |
| F14a | Videos in the channel's playlists that were uploaded by **other** channels are skipped by default | Must | Shown in the preview as `other channel – skipped` | ✅ |

### Run control
| ID | Requirement | Priority | Acceptance criteria | Src |
|---|---|---|---|---|
| F12 | Asks for the **output folder at startup**; pressing Enter uses `output\` in the project folder | Must | The folder is created if missing and checked to be writable. A path that can't be used is rejected with a reason and the question repeats. A folder that already has a `manifest.json` is treated as a resume. | ✅ |
| F17 | **Preview before download:** each video's title, length and upload date, the total count, how many will be skipped as already verified, how many need attention, and an estimated total size | Must | Nothing downloads until you confirm. Answering "no" exits and records the queued videos as `planned`. | ✅ |
| F15 | Step-by-step guided prompts started from `run.bat`; they replace the temporary `--video` mode | Must | Someone who doesn't code can complete a backup using only the prompts | 🔎 (Increment 5) |

### Download and storage
| ID | Requirement | Priority | Acceptance criteria | Src |
|---|---|---|---|---|
| F5 | Best video and best audio (`bv*+ba/b`), merged into **MKV** without re-encoding | Must | The saved resolution and frame rate equal the best available; codecs are unchanged | 🔎 |
| F6 | Saves supporting files next to each video: `.description`, `.info.json`, thumbnail, and **uploaded captions only** (no auto-generated captions, no live chat) | Must | All of them are present beside the MKV | 🔎 |
| F9 | Layout: `<out>\<Channel>\<YYYY-MM-DD> - <Title ≤80 bytes> [<id>]\<Title> [<id>].mkv`, plus `<id>.*` supporting files; `manifest.json` and `report.csv` at the top of the output folder | Must | Matches the layout for every verified video | ✅🔎 |

### Verification
| ID | Requirement | Priority | Acceptance criteria | Src |
|---|---|---|---|---|
| F7 | ffprobe check after every download: video and audio present; duration within **±2.0 s** of YouTube's; height equals the best available; frame rate within **±0.5** of the best available; codecs equal what was downloaded | Must | A video only counts as done once it is `verified` | 🔎 |
| F8 | **Re-runs skip finished videos:** a video is skipped only if it is `verified` **and** its file still exists | Must | A second run makes no download calls for it; deleting the MKV makes the next run download it again | 🔎 |

### Failure handling
| ID | Requirement | Priority | Acceptance criteria | Src |
|---|---|---|---|---|
| F10 | Keep going after a failure; yt-dlp retries: 10 for network errors, 10 for fragments, 3 for file access | Must | If video 3 of 10 fails, videos 4–10 are still processed | ✅🔎 |
| F10a | After the first pass, each failed video is retried **once** more in the same run | Must | A temporary failure can end up `verified` | ✅ |
| F10b | A file that fails the check is moved to `.failed\<id>\`, and the next attempt starts clean | Must | No unverified MKV stays in the channel folder | ✅ |
| F10c | After **3** runs in which a video failed, it is marked `failed – needs attention` and no longer retried automatically | Must | It is skipped and flagged in the preview | ✅ |
| F10d | If a run is interrupted mid-download, that video is queued again on the next run | Must | `downloading` is reset to `queued` when the manifest loads | 🔎 |

### Records and reporting
| ID | Requirement | Priority | Acceptance criteria | Src |
|---|---|---|---|---|
| F11 | `report.csv` (UTF-8 with a byte-order mark so Excel reads it correctly), rebuilt from the manifest after every change | Must | Opens correctly in Excel, including non-English titles | 🔎 |
| F11a | End-of-run summary: verified / skipped / failed counts, with each failure's reason | Must | Printed and also written to the log | ✅ |
| F13 | Records each video's **playlist membership** (id, title, position) in `details.json`; adds `playlist_count` and `playlists` columns to the report | Must | A video in 2 playlists lists both | ✅ |
| F16 | `manifest.json` is the single record of each video's status. It is written safely (temp file, then replace) and the previous version is kept as `.bak` | Must | A corrupt manifest is recovered from `.bak` | 🔎 |

### Description details (Increment 2)
| ID | Requirement | Priority | Acceptance criteria | Src |
|---|---|---|---|---|
| F19 | Reads from each description: **author, chapters, hashtags, credits, links** → `<id>.details.json` (the playlists field is filled by F13) | Must | All fields are present for the 3 sample descriptions | ✅ |
| F19-author | Author order, first match wins: labelled line (`Author:`, `Speaker:`, `Presented by:`…) → a person's name at the start or end of the title, confirmed by the description → biography sentence → channel name. `author_source` records which rule matched. | Must | Each sample produces the expected author and source | ✅ |
| F19-chapters | Timestamp lines in the description are recorded as chapters in `details.json` **only**. They are **never embedded**, because schedules and clock times look like chapters and an embedded list is permanent. Only YouTube's own chapters are embedded. | Must | `embedded_chapters_source` ∈ {youtube, none} | ✅ (revised 2026-11-02) |
| F19-hashtags | `#words` (not inside URLs), duplicates removed ignoring case | Must | | ✅ |
| F19-credits | `Role: Name` lines and sentences with "provided by", "in association with" or "possible through" | Must | Stored in `details.json` only | ✅ |
| F19-links | http(s) and `www.` URLs, each labelled with the text around it, duplicates removed | Must | | ✅ |
| F19a | Report columns: `author`, `author_source`, `chapter_count`, `hashtag_count`, `link_count` | Must | | 🔎 |
| F19b | Embedded in the MKV without re-encoding: **YouTube's** chapters, and the author as the **artist tag only** (no credits or hashtags) | Must | ffprobe shows the expected chapter count and artist tag | ✅🔎 |

## 3. Nonfunctional Requirements
| ID | Requirement | Priority | Acceptance criteria | Src |
|---|---|---|---|---|
| NF1 | Never re-encode | Must | Codec check in F7 | 🔎 |
| NF2 | Free-space check against the preview's size estimate | Must | A warning appears before you confirm if space is short | ✅ |
| NF3 | **Nothing is downloaded twice:** re-running a fully verified backup downloads 0 bytes | Must | The log says "already verified - skipping (0 bytes downloaded)" | 🔎 |
| NF11 | A random pause of **5–15 s** between videos | Must | Visible in the log | ✅ |
| NF11a | On HTTP 429 or a rate-limit error: wait **10 min**, then retry, up to **3** times | Must | Logged | ✅ |
| NF11b | On the "confirm you're not a bot" block: save the manifest and report, exit with a clear message, leave the rest `queued` | Must | The next run resumes | ✅ |
| NF11c | No download speed cap by default | — | | ✅ |
| NF4 | Never uses cookies, accounts or credentials | Must | The yt-dlp options contain no cookie or auth settings | 🔎 |
| NF5 | Folder and file names safe for Windows; titles cut to 80 bytes | Must | | 🔎 |
| NF6 | Windows 10/11 x64; Python 3.12 tested (3.10+ supported); PowerShell 7 or 5.1 | Must | `setup.ps1` succeeds on both PowerShell versions | 🔎 |
| NF7 | One log file per run, `logs\run-<UTC>.log`: full detail in the file, normal messages on screen | Must | | 🔎 |
| NF8 | Reproducible setup: `requirements.lock.txt`; ffmpeg and Deno checked against their published SHA-256 checksums | Must | A checksum mismatch stops setup | 🔎 |
| NF9 | External programs are run without a shell, with fixed arguments and a time limit | Must | | 🔎 |
| NF10 | Tool versions are written to the log and the manifest on every run | Must | | 🔎 |

## 4. Architecture Decisions (recovered)
1. yt-dlp is used **as a Python library**, not by calling its command line.
2. `manifest.json` is the **single record** of each video's status.
3. yt-dlp **nightly** builds, frozen into `requirements.lock.txt` once a version passes testing.
4. Chapters: **only YouTube's own chapters are embedded.** Description chapters are recorded in `details.json` but never embedded. (Revised 2026-11-02; this replaces "fall back to description chapters when YouTube has none".)
5. Captions: **only those the uploader added**; no auto-generated captions.

## 5. Increment Plan
| # | Scope | State |
|---|---|---|
| 0 | Skeleton, `setup.ps1`, launcher, logging, dependency check | Merged |
| 1 | One video end to end: download → check → manifest → report | Merged |
| 2 | F19, F19a, F19b: description details | Merged 2026-11-03 (PR #2); review fixes R2, R4–R7; validated on Windows (R1) |
| 3 | F1–F4a, F13, F14, F14a: all four input types, line-numbered errors, finding videos via playlists, playlist columns | In progress on `increment-3-inputs` (step 1 of 5: link classification and list parsing) |
| 4 | F17, F10–F10c, F11a, NF2, NF11*: preview, the multi-video loop, failure handling, pacing | ✅ Planned |
| 5 | F12, F15: guided prompts, output-folder prompt, README for end users | 🔎 |

## 6. MVP
Increments 0–5 together: a guided, resumable, verified backup of a channel, playlist, single video or list of videos.

## 7. Exclusions
- Members-only or paid videos, and anything else that needs a sign-in
- Upcoming or live streams
- Auto-generated captions and live chat
- Re-encoding or format conversion
- Embedding chapters taken from descriptions
- Ongoing or scheduled syncing (this is a **one-time** backup)
- macOS and Linux support

## 8. Open Assumptions
- None open. The scope of Increments 3 and 4 is reconstructed, and you confirmed it on 2026-11-02.
