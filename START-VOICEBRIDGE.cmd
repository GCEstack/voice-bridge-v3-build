@echo off
REM ============================================================
REM  VoiceBridge V3 — integrated build candidate launcher
REM  Build: 2026-10-01 · VoiceBridge V3 integrated build v0.1.0
REM ------------------------------------------------------------
REM  This is the V3 CANDIDATE. The live bridge is still the frozen
REM  working tree at ..\voice-bridge\ (protected, never modified).
REM  Do not point Don at this launcher until Gate P is reported green.
REM
REM  AssemblyAI key: read from .env in THIS directory. It is NOT
REM  bundled, NOT copied from the live tree, and never printed.
REM  Ask Don to drop the .env in before the real-usage run.
REM
REM  Interpreter resolution, in order:
REM    1. .\.venv\Scripts\python.exe          (this tree, preferred)
REM    2. ..\voice-bridge\.venv\Scripts\python.exe  (frozen baseline)
REM       Read-only borrow of the interpreter. Running it does not
REM       modify the protected tree.
REM    3. py -3
REM ------------------------------------------------------------
cd /d "%~dp0"
chcp 65001 >nul

set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY if exist "..\voice-bridge\.venv\Scripts\python.exe" set "PY=..\voice-bridge\.venv\Scripts\python.exe"

if defined PY (
    "%PY%" -m src.voice_bridge %*
) else (
    echo [WARN] No local or baseline venv found — falling back to py -3.
    py -3 -m src.voice_bridge %*
)

echo.
echo VoiceBridge V3 candidate exited. Press any key to close.
pause >nul
