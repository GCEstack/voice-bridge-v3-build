@echo off
REM ============================================================
REM  VoiceBridge - the ONE launcher Don uses.
REM  Tree: voice-bridge-v3-build (integrated build, 2026-10-02)
REM ------------------------------------------------------------
REM  Don launches exactly one thing. This file is that thing.
REM
REM  Repair log 2026-10-02 (Nico, VoiceBridge recovery):
REM   The previous revision of this launcher had been replaced with a
REM   hard-coded one that (a) dropped the documented interpreter
REM   resolution cascade, (b) parsed the borrowed .env with a fragile
REM   loop, and (c) invoked the handoff producer directly instead of
REM   through its own idempotent launcher. All three are restored
REM   below.
REM
REM  RUNTIME MODEL
REM    Source      : this tree
REM    Interpreter : .\.venv if present, else the frozen baseline's
REM                   ..\voice-bridge\.venv (read-only borrow),
REM                   else py -3
REM    Credential  : .\.env if present, else ..\voice-bridge\.env.
REM                   Never copied into this tree, never printed.
REM    The frozen tree ..\voice-bridge\ is READ ONLY. Nothing here
REM    writes to it.
REM
REM  QUEUE PROJECTION (automatic - Don never runs plumbing)
REM    The review panel is READ ONLY and must never invoke the
REM    producer. Projection therefore happens here, ONCE, at
REM    launch, through command-center's own idempotent launcher,
REM    plus the durable Tier-3 poller it starts:
REM       1. start-queue-watch.cmd  -> hidden detached 15s poller
REM       2. one projection pass     -> the registry is correct
REM                                     AT OPEN, even when the
REM                                     poller's fingerprint gate
REM                                     sees no source change
REM    Every failure here is a WARNING. Dictation must never be
REM    blocked by the queue.
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul

set "BASELINE=..\voice-bridge"
set "CC=C:\Users\Dekan AI Brother\GCE_DON\command-center"
set "ENV_LOCAL=%CD%\.env"
set "ENV_BASELINE=%CD%\..\voice-bridge\.env"

REM ------------------------------------------------------------
REM 1. Interpreter resolution (documented cascade)
REM ------------------------------------------------------------
set "PY="
if exist "%CD%\.venv\Scripts\python.exe" set "PY=%CD%\.venv\Scripts\python.exe"
if not defined PY if exist "%CD%\..\voice-bridge\.venv\Scripts\python.exe" set "PY=%CD%\..\voice-bridge\.venv\Scripts\python.exe"

REM ------------------------------------------------------------
REM 2. Credential resolution - read only, never echoed
REM ------------------------------------------------------------
set "ENV_SOURCE="
if exist "%ENV_LOCAL%" set "ENV_SOURCE=%ENV_LOCAL%"
if not defined ENV_SOURCE if exist "%ENV_BASELINE%" set "ENV_SOURCE=%ENV_BASELINE%"

if defined ENV_SOURCE (
    for /f "usebackq tokens=1,* delims==" %%a in ("%ENV_SOURCE%") do (
        if "%%a"=="ASSEMBLYAI_API_KEY" set "ASSEMBLYAI_API_KEY=%%b"
    )
)

if defined ASSEMBLYAI_API_KEY (
    echo [INFO] AssemblyAI credential loaded from %ENV_SOURCE%
) else (
    echo [WARN] No ASSEMBLYAI_API_KEY found in .\.env or ..\voice-bridge\.env
    echo [WARN] Dictation will not start until one is present. The queue still runs.
)

REM ------------------------------------------------------------
REM 3. Queue projection - best effort, never fatal
REM ------------------------------------------------------------
where node >nul 2>&1
if errorlevel 1 (
    echo [WARN] node not on PATH - handoff queue will show its last projection only.
) else (
    echo [INFO] Starting durable queue watcher in command-center - 15s poll...
    REM Not gated on errorlevel: the launcher is idempotent and self-reporting,
    REM and its exit code is not a reliable success signal. Its own evidence is
    REM command-center\queue-refresh.log and queue-refresh.pid.
    call "%CC%\start-queue-watch.cmd" >nul 2>&1
    echo [INFO] Queue watcher launcher returned - see command-center\queue-refresh.log
    echo [INFO] Projecting handoff queue once so the panel opens on live state...
    pushd "%CC%"
    node routing\handoff_registry_producer.js >nul 2>&1
    if errorlevel 1 (
        echo [WARN] projection returned non-zero - panel will show the last projection
    ) else (
        echo [INFO] Queue projected
    )
    popd
)

REM ------------------------------------------------------------
REM 4. Run
REM ------------------------------------------------------------
echo.
echo [INFO] Source     : %CD%
echo [INFO] Interpreter: %PY%
echo.

if defined PY (
    "%PY%" -m src.voice_bridge %*
) else (
    echo [WARN] No local or baseline venv found - falling back to py -3.
    py -3 -m src.voice_bridge %*
)

echo.
echo VoiceBridge exited. Press any key to close.
pause >nul
endlocal
