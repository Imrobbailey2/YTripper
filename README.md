# YTripper

YTripper makes a one-time, verified backup of a YouTube channel's videos in the best quality YouTube stores. It's a guided script for Windows, built on [yt-dlp](https://github.com/yt-dlp/yt-dlp) (used as a Python library), ffmpeg/ffprobe and Deno.

> **Status: Increment 0 (project skeleton).** Only the environment setup and the dependency check work so far. The backup itself comes in later increments.

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
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

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
run.bat --versions        & rem dependency check
.venv\Scripts\python.exe -m pytest
```

## Layout

```
src/ytripper/     application package
tests/            pytest suite
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
