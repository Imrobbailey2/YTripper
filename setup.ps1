<#
.SYNOPSIS
    One-time environment setup for YTripper on Windows 10/11 x64.

.DESCRIPTION
    1. Locates Python 3.10+ (3.12 preferred) and creates .venv
    2. Installs Python dependencies:
         - from requirements.lock.txt if present (reproducible), otherwise
         - from requirements.in with --pre (yt-dlp nightly) and freezes the result
           into requirements.lock.txt
    3. Downloads ffmpeg/ffprobe (yt-dlp/FFmpeg-Builds) and Deno (denoland/deno)
       into .\tools, verifying each archive against the SHA-256 published
       alongside it. Any mismatch aborts setup.
    4. Prints all dependency versions via `python -m ytripper --versions`
       and fails if anything is missing.

.PARAMETER Refresh
    Ignore requirements.lock.txt and existing tools; re-resolve the latest
    nightly yt-dlp and re-download ffmpeg/Deno.

.PARAMETER SkipTools
    Do not download ffmpeg/ffprobe/Deno (use ones already on PATH).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\setup.ps1
#>
[CmdletBinding()]
param(
    [switch]$Refresh,
    [switch]$SkipTools
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is far faster without the progress bar
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root      = $PSScriptRoot
$Venv      = Join-Path $Root '.venv'
$VenvPy    = Join-Path $Venv 'Scripts\python.exe'
$ToolsDir  = Join-Path $Root 'tools'
$Downloads = Join-Path $ToolsDir '_downloads'
$LockFile  = Join-Path $Root 'requirements.lock.txt'
$ToolsLock = Join-Path $ToolsDir 'tools.lock.json'

$Sources = @{
    ffmpeg = @{
        Url       = 'https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip'
        SumUrl    = 'https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/checksums.sha256'
        FileName  = 'ffmpeg-master-latest-win64-gpl.zip'
        Binaries  = @('ffmpeg.exe', 'ffprobe.exe')
    }
    deno = @{
        Url       = 'https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip'
        SumUrl    = 'https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip.sha256sum'
        FileName  = 'deno-x86_64-pc-windows-msvc.zip'
        Binaries  = @('deno.exe')
    }
}

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Fail([string]$Message) { Write-Host "SETUP FAILED: $Message" -ForegroundColor Red; exit 1 }

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments, [string]$What)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { Fail "$What (exit code $LASTEXITCODE)" }
}

function Find-Python {
    # Prefer the py launcher with 3.12, then any python on PATH that is >= 3.10.
    $candidates = @(
        @{ Exe = 'py';      Args = @('-3.12') },
        @{ Exe = 'py';      Args = @('-3') },
        @{ Exe = 'python';  Args = @() },
        @{ Exe = 'python3'; Args = @() }
    )
    foreach ($c in $candidates) {
        if (-not (Get-Command $c.Exe -ErrorAction SilentlyContinue)) { continue }
        try {
            $ver = & $c.Exe @($c.Args + @('-c', 'import sys; print("%d.%d" % sys.version_info[:2])')) 2>$null
        } catch { continue }
        if ($LASTEXITCODE -ne 0 -or -not $ver) { continue }
        $parts = $ver.Trim().Split('.')
        if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 10) {
            return @{ Exe = $c.Exe; Args = $c.Args; Version = $ver.Trim() }
        }
    }
    return $null
}

function Get-PublishedSha256 {
    <# Downloads a checksum file and returns the 64-hex digest for $FileName.
       Handles both "<hash>  <file>" lists and single-hash files. #>
    param([string]$SumUrl, [string]$FileName)
    $text = (Invoke-WebRequest -Uri $SumUrl -UseBasicParsing).Content
    if ($text -is [byte[]]) { $text = [Text.Encoding]::UTF8.GetString($text) }
    foreach ($line in ($text -split "`r?`n")) {
        if ($line -match [regex]::Escape($FileName) -and $line -match '([0-9a-fA-F]{64})') { return $Matches[1].ToLower() }
    }
    $all = [regex]::Matches($text, '[0-9a-fA-F]{64}')
    if ($all.Count -eq 1) { return $all[0].Value.ToLower() }
    Fail "Could not find a SHA-256 for $FileName in $SumUrl"
}

function Install-Tool {
    param([string]$Name, [hashtable]$Src)
    $missing = $Src.Binaries | Where-Object { -not (Test-Path (Join-Path $ToolsDir $_)) }
    if (-not $Refresh -and -not $missing) {
        Write-Host "    $Name already present (use -Refresh to re-download)"
        return $null
    }
    New-Item -ItemType Directory -Force -Path $Downloads | Out-Null
    $zip = Join-Path $Downloads $Src.FileName

    Write-Host "    fetching published checksum..."
    $expected = Get-PublishedSha256 -SumUrl $Src.SumUrl -FileName $Src.FileName

    Write-Host "    downloading $($Src.Url)"
    Invoke-WebRequest -Uri $Src.Url -OutFile $zip -UseBasicParsing
    $actual = (Get-FileHash -Algorithm SHA256 -Path $zip).Hash.ToLower()
    if ($actual -ne $expected) {
        Remove-Item -Force $zip
        Fail "Checksum mismatch for $($Src.FileName): expected $expected, got $actual"
    }
    Write-Host "    checksum OK ($actual)"

    $extract = Join-Path $Downloads "$Name-extract"
    if (Test-Path $extract) { Remove-Item -Recurse -Force $extract }
    Expand-Archive -Path $zip -DestinationPath $extract -Force
    foreach ($bin in $Src.Binaries) {
        $found = Get-ChildItem -Path $extract -Recurse -Filter $bin | Select-Object -First 1
        if (-not $found) { Fail "$bin not found inside $($Src.FileName)" }
        Copy-Item -Force $found.FullName (Join-Path $ToolsDir $bin)
    }
    Remove-Item -Recurse -Force $extract
    Remove-Item -Force $zip
    return [ordered]@{ name = $Name; url = $Src.Url; sha256 = $actual; installed_utc = (Get-Date).ToUniversalTime().ToString('o') }
}

# --- 1. Python + venv -------------------------------------------------------
Write-Step 'Locating Python 3.10+ (3.12 preferred)'
$py = Find-Python
if (-not $py) { Fail 'Python 3.10 or newer not found. Install Python 3.12 from https://www.python.org/downloads/windows/ (tick "Add python.exe to PATH") and re-run.' }
Write-Host "    found Python $($py.Version) via '$($py.Exe) $($py.Args -join ' ')'"
if ($py.Version -ne '3.12') { Write-Warning "Python 3.12 is the tested version; $($py.Version) should work but is untested." }

if (-not (Test-Path $VenvPy)) {
    Write-Step 'Creating virtual environment (.venv)'
    Invoke-Checked -Exe $py.Exe -Arguments ($py.Args + @('-m', 'venv', $Venv)) -What 'venv creation failed'
}

# --- 2. Python dependencies -------------------------------------------------
Write-Step 'Installing Python dependencies'
Invoke-Checked -Exe $VenvPy -Arguments @('-m', 'pip', 'install', '--disable-pip-version-check', '-q', '--upgrade', 'pip') -What 'pip upgrade failed'
if ((Test-Path $LockFile) -and -not $Refresh) {
    Write-Host '    installing pinned versions from requirements.lock.txt'
    Invoke-Checked -Exe $VenvPy -Arguments @('-m', 'pip', 'install', '--disable-pip-version-check', '-q', '-r', $LockFile) -What 'pip install (lock) failed'
} else {
    Write-Host '    resolving latest versions (yt-dlp nightly via --pre) from requirements.in'
    Invoke-Checked -Exe $VenvPy -Arguments @('-m', 'pip', 'install', '--disable-pip-version-check', '-q', '--upgrade', '--pre', '-r', (Join-Path $Root 'requirements.in')) -What 'pip install failed'
    $frozen = & $VenvPy -m pip freeze --exclude-editable
    if ($LASTEXITCODE -ne 0) { Fail 'pip freeze failed' }
    $header = "# Generated by setup.ps1 on $((Get-Date).ToUniversalTime().ToString('o')). Commit once tests pass."
    Set-Content -Path $LockFile -Value (@($header) + $frozen) -Encoding UTF8
    Write-Host '    wrote requirements.lock.txt'
}
Invoke-Checked -Exe $VenvPy -Arguments @('-m', 'pip', 'install', '--disable-pip-version-check', '-q', '-r', (Join-Path $Root 'requirements-dev.txt')) -What 'pip install (dev) failed'

# --- 3. External tools ------------------------------------------------------
if (-not $SkipTools) {
    Write-Step 'Installing ffmpeg/ffprobe and Deno into .\tools (SHA-256 verified)'
    New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
    $records = @()
    foreach ($name in @('ffmpeg', 'deno')) {
        Write-Host "  - $name"
        $rec = Install-Tool -Name $name -Src $Sources[$name]
        if ($rec) { $records += $rec }
    }
    if ($records.Count -gt 0) {
        $existing = @()
        if (Test-Path $ToolsLock) { $existing = @(Get-Content $ToolsLock -Raw | ConvertFrom-Json) | Where-Object { $records.name -notcontains $_.name } }
        ConvertTo-Json -InputObject @($existing + $records) -Depth 4 | Set-Content -Path $ToolsLock -Encoding UTF8
    }
    if (Test-Path $Downloads) { Remove-Item -Recurse -Force $Downloads }
} else {
    Write-Step 'Skipping tool download (-SkipTools); ffmpeg/ffprobe/deno must be on PATH'
}

# --- 4. Verify ---------------------------------------------------------------
Write-Step 'Verifying environment'
Push-Location $Root
try {
    $env:PYTHONPATH = Join-Path $Root 'src'
    & $VenvPy -m ytripper --versions
    $code = $LASTEXITCODE
} finally { Pop-Location }
if ($code -ne 0) { Fail 'One or more dependencies are missing (see above).' }

Write-Host ''
Write-Host 'Setup complete. Run tests with:  .\.venv\Scripts\python.exe -m pytest' -ForegroundColor Green
Write-Host 'Start YTripper with:             .\run.bat' -ForegroundColor Green
exit 0
