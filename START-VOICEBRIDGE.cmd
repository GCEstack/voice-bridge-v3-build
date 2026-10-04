@echo off
REM ============================================================
REM  VoiceBridge - the ONE launcher Don uses.
REM  Tree: voice-bridge-v3-build (sole product tree, 2026-10-03)
REM ------------------------------------------------------------
REM  Don launches exactly one thing. This file is that thing.
REM
REM  RESET 2026-10-03 (Nico, Don authority: queue plumbing reset)
REM    1. This tree now OWNS its runtime. The interpreter borrow from
REM       ..\voice-bridge\.venv and the credential borrow from
REM       ..\voice-bridge\.env are both GONE. v3-build has its own
REM       .venv and its own .env.
REM    2. The QUEUE PROJECTION BLOCK IS DELETED. It used to start the
REM       Tier-3 watcher and shell out to the legacy producer
REM       (routing\handoff_registry_producer.js), which read
REM       06_HANDOFFS + ai-inbox. That whole queue source is retired.
REM    3. The queue is now FED BY INGEST, not by projection:
REM         python -m src.completion submit <artifact.json>
REM       Nothing in this launcher touches the queue. The panel only
REM       reads it. Dictation can never be blocked by queue state.
REM
REM  RUNTIME MODEL
REM    Source      : this tree
REM    Interpreter : .\.venv\Scripts\python.exe   (required, owned here)
REM    Credential  : .\.env                      (required, owned here)
REM    Neither is ever printed, copied out, or borrowed.
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul

set "PY=%CD%\.venv\Scripts\python.exe"
set "ENVF=%CD%\.env"

REM ------------------------------------------------------------
REM 1. Runtime must be local. No borrow cascade any more.
REM ------------------------------------------------------------
if not exist "%PY%" (
    echo [FATAL] This tree has no interpreter at:
    echo         %PY%
    echo         It previously borrowed ..\voice-bridge\.venv.
    echo         That borrow has ended. Create it with:
    echo             C:\Python314\python.exe -m venv .venv
    echo             .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 2
)

REM ------------------------------------------------------------
REM 2. Credential must be local. Read only, never echoed.
REM ------------------------------------------------------------
if not exist "%ENVF%" (
    echo [FATAL] No .env in this tree:
    echo         %ENVF%
    echo         Without ASSEMBLYAI_API_KEY the mic cannot reach STT.
    echo         The key is never printed and never logged.
    echo.
    pause
    exit /b 2
)

for /f "usebackq tokens=1,* delims==" %%a in ("%ENVF%") do (
    if "%%a"=="ASSEMBLYAI_API_KEY" set "ASSEMBLYAI_API_KEY=%%b"
)

if defined ASSEMBLYAI_API_KEY (
    echo [INFO] AssemblyAI credential loaded from %ENVF%
) else (
    echo [WARN] .env present but ASSEMBLYAI_API_KEY is empty.
    echo [WARN] Dictation will not reach STT. The queue is unaffected.
)

REM ------------------------------------------------------------
REM 3. Run. No queue plumbing here, by design.
REM ------------------------------------------------------------
echo.
echo [INFO] Source     : %CD%
echo [INFO] Interpreter : %PY%
echo [INFO] Queue      : %CD%\queue  (fed by: python -m src.completion submit)
echo.

"%PY%" -m src.voice_bridge %*

echo.
echo VoiceBridge exited. Press any key to close.
pause >nul
endlocal