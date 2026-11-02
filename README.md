# YTripper

YTripper makes a one-time, verified backup of a YouTube channel's videos in the best quality YouTube stores. It's a guided script for Windows, built on [yt-dlp](https://github.com/yt-dlp/yt-dlp) (used as a Python library), ffmpeg/ffprobe and Deno.

> **Status: Increment 2 (description details).** A single video can be backed up end to end with `--video`: download, ffprobe verification, description details, manifest and report. Channel, playlist and link-list input (Increment 3), the preview and multi-video run (Increment 4) and the guided prompts (Increment 5) are still to come. See [`docs/BUILD_SPEC.md`](docs/BUILD_SPEC.md) for the full specification.

## Scope

- Public and unlisted videos only. You need the channel link plus the links to any unlisted videos.
- No sign-in: no cookies or account credentials are ever used or stored.
- Videos are saved as MKV with the best video and audio streams, never re-encoded.
- Each video is checked with ffprobe after download.
- Reruns are safe: finished videos are skipped and only failed ones are retried.
- Pulls these details from each description: chapters, hashtags, credits, author and links.

## Requirements

- Windows 10/11 x64
- Python 3.12 (3.10+ should work but hasn't been tested), installed from python.org with "Add python.exe to PATH" ticked
- Internet access during setup

## Setup

```powershell
pwsh -ExecutionPolicy Bypass -File .\setup.ps1
```

PowerShell 7 (`pwsh`) is recommended. Windows PowerShell 5.1 (`powershell -ExecutionPolicy Bypass -File .\setup.ps1`) is also supported. If no suitable Python is found, setup lists each candidate it tried and why it was rejected.

Setup does the following:

1. Creates `.venv` and installs the Python dependencies.
   - If `requirements.lock.txt` exists, it installs those exact versions.
   - Otherwise it installs the latest **nightly** yt-dlp and writes the resolved versions to `requirements.lock.txt`.
2. Downloads `ffmpeg.exe`, `ffprobe.exe` and `deno.exe` into `tools\`. Each archive is checked against the SHA-256 checksum its publisher releases alongside it.
3. Runs `python -m ytripper --versions` and fails if any dependency is missing.

| Switch | Effect |
|---|---|
| `-Refresh` | Ignores the lock file and existing tools: gets the newest nightly yt-dlp and downloads ffmpeg and Deno again |
| `-SkipTools` | Uses ffmpeg, ffprobe and Deno from `PATH` instead of downloading them |

## Usage (current)

```bat
run.bat --versions                                   & rem dependency check
run.bat --video https://youtu.be/VIDEO_ID            & rem back up one video into .\output
run.bat --video https://youtu.be/VIDEO_ID --output D:\Backup
.venv\Scripts\python.exe -m pytest                   & rem test suite
```

`--video` is a temporary test mode; the guided prompts replace it in Increment 5. Any YouTube video link works (`youtu.be`, `watch?v=`, `shorts/`, `live/`, `embed/`; tracking parameters such as `?si=` are ignored).

| Option | Default | Meaning |
|---|---|---|
| `--output DIR` | `output\` in the project folder | Backup folder |
| `--log-dir DIR` | `logs\` | Where run logs are written |
| `--tools-dir DIR` | `tools\` | Where ffmpeg, ffprobe and Deno are looked for first |

Exit codes: `0` verified or already done, `1` log folder can't be created, `2` invalid link or unusable output folder, `3` missing dependency, `4` no mode given, `5` download or verification failed.

## What a backup contains

```
<output>\
  manifest.json            status of every video (single source of truth; .bak kept)
  report.csv               one row per video; UTF-8 with BOM for Excel
  <Channel>\
    <YYYY-MM-DD> - <Title> [<id>]\
      <Title> [<id>].mkv   best video + best audio, stream copy, verified with ffprobe
      <id>.description     original description text
      <id>.info.json       full yt-dlp metadata
      <id>.jpg / .webp     thumbnail
      <id>.<lang>.vtt      captions the uploader added (no auto-generated captions)
      <id>.details.json    author, chapters, hashtags, credits and links parsed from the description
```

What is embedded inside the MKV:

- **Chapters:** YouTube's own chapters only. Timestamps found in the description are recorded in `details.json` but never embedded.
- **Artist tag:** the author. The first match wins: an `Author:`-style label → a name in the title that the description confirms → a biography sentence → the channel name.

A video counts as done only when ffprobe confirms all of the following:

- it has both video and audio;
- its duration is within ±2 s of YouTube's;
- its resolution and frame rate are the best YouTube offered;
- its codecs are unchanged;
- the expected chapters and artist tag are present.

Report columns: `video_id, title, channel, status, height, fps, vcodec, acodec, duration_s, size_bytes, path, author, author_source, chapter_count, hashtag_count, link_count, attempts, error`. Text that starts with `=`, `+`, `-` or `@` is prefixed with `'` so Excel can't run it as a formula.

## Layout

```
src/ytripper/     application package
tests/            pytest suite
docs/             build specification
tools/            ffmpeg.exe, ffprobe.exe, deno.exe (downloaded; not committed)
samples/          sample descriptions for parser tests
logs/             run logs (not committed)
setup.ps1         one-time environment setup
run.bat           launcher
```

## Updating yt-dlp before the real run

YouTube changes often break downloaders, so update just before backing up:

```powershell
.\setup.ps1 -Refresh
.venv\Scripts\python.exe -m pytest
```

Once the tests and a one-video test pass, commit the new `requirements.lock.txt`.
