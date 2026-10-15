@echo off
rem YTripper launcher. Run setup.ps1 once before first use.
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo YTripper is not set up yet.
    echo Run:  powershell -ExecutionPolicy Bypass -File "%ROOT%setup.ps1"
    exit /b 1
)

rem Project tools first on PATH for this process only; UTF-8 console I/O.
set "PATH=%ROOT%tools;%PATH%"
set "PYTHONPATH=%ROOT%src"
set "PYTHONUTF8=1"
chcp 65001 >nul

"%PY%" -m ytripper %*
exit /b %ERRORLEVEL%
