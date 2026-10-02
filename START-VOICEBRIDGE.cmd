@echo off
REM ============================================================
REM  VoiceBridge V3 — isolated surgical acceptance candidate
REM  Build: 2026-10-02 · VoiceBridge V3 consolidated
REM ------------------------------------------------------------
REM  This is the ISOLATED CANDIDATE. The original working VoiceBridge
REM  at ..\voice-bridge\ is PROTECTED and NEVER MODIFIED.
REM
REM  RUNTIME MODEL (Option B — isolated verification):
REM    - Python: borrowed from original .venv (read-only)
REM    - Credentials: loaded from original .env (not copied)
REM    - Source: this candidate tree (isolated)
REM    - Original tree: untouched, unmodified
REM ------------------------------------------------------------
cd /d "%~dp0"
chcp 65001 >nul

REM Explicit runtime contract:
REM   1. Use original .venv as PRIMARY (candidate has no local venv)
REM   2. Load credentials from original .env (not copied)
set "PY=..\voice-bridge\.venv\Scripts\python.exe"
set "ENV_SOURCE=..\voice-bridge\.env"

REM Load credentials from original .env without copying
if exist "%ENV_SOURCE%" (
    for /f "usebackq tokens=1,* delims==" %%a in ("%ENV_SOURCE%") do (
        if "%%a"=="ASSEMBLYAI_API_KEY" set "%%a=%%b"
    )
    echo [INFO] Credentials loaded from original .env
) else (
    echo [ERROR] Original .env not found at %ENV_SOURCE%
    echo [ERROR] Cannot start candidate without credentials
    pause
    exit /b 1
)

REM Verify Python exists
if not exist "%PY%" (
    echo [ERROR] Original .venv not found at %PY%
    echo [ERROR] Cannot start candidate without runtime
    pause
    exit /b 1
)

REM Run producer once at startup to ensure fresh registry
REM Refresh button will re-run producer for manual refresh
echo [INFO] Running handoff producer...
cd /d "C:\Users\Dekan AI Brother\GCE_DON\command-center"
node routing\handoff_registry_producer.js
if errorlevel 1 (
    echo [WARN] Producer returned non-zero, continuing anyway
) else (
    echo [INFO] Producer completed successfully
)
cd /d "%~dp0"
echo.

REM Execute candidate with:
REM   - interpreter: original .venv (borrowed)
REM   - working dir: this candidate
REM   - source: this candidate's src/
REM   - config: this candidate's config.json
REM   - credentials: from original .env
echo [INFO] Starting VoiceBridge V3 candidate...
echo [INFO] Python: %PY%
echo [INFO] Source: %CD%
echo [INFO] Credentials: %ENV_SOURCE%
echo.
"%PY%" -m src.voice_bridge %*

echo.
echo VoiceBridge V3 candidate exited.
pause >nul
