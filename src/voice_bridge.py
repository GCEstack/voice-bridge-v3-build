"""Voice Bridge — hands-free, wake-word voice dictation on AssemblyAI.

Gated on a wake word. While SLEEPING the mic streams continuously via
AssemblyAI Universal-3.5 Pro but nothing is typed; ambient speech is ignored.
Saying a wake word (config `wake_words`, e.g. "hey keel") ARMs the bridge.
While ARMED, finalized transcripts are typed verbatim (or run as commands)
until the pause command ("sleep") or the armed idle timeout.

Transcript flow (V3 integrated build, 2026-10-01):
    Mic -> AssemblyAI (always-on) -> finalized Turn -> on_transcript()
        -> _turn_queue -> _engine_loop:  V3 durable transcript FIRST (G6)
             -> _final_queue -> _dispatch_loop -> _handle_final()
                 -> wake word? -> ARM (+ strip wake word, dispatch payload)
                 -> SLEEPING? -> ignore
                 -> ARMED: session command? (pause/resume/quit) -> execute
                          -> quick command? (copy/paste/...) -> execute_command
                          -> else type verbatim

V3 SURGERY POINTS (the only four places the engine meets the shell):
    A  STT path   - the engine's full-fidelity transcript feeds the dictation
                    buffer. Copy Text / typing receive the COMPLETE text. The
                    baseline 80-char truncation at intent.py:102 is gone.
    B  Queue panel - read path UNCHANGED. queue_panel.py is untouched and still
                    reads the same ``queue`` registry. No honesty work here.
    C  Partials   - ephemeral. Zero partials reach disk; exactly ONE durable
                    transcript exists per finished utterance.
    D  Health     - engine health (STT connection + capture loop) is surfaced in
                    the status line. Observable silence is a fault, never quiet.

Single-instance: a Windows named mutex prevents two bridges opening the mic.

Run:
    python -m src.voice_bridge            # GUI, wake-word
    python -m src.voice_bridge --self-test  # headless state-machine check
"""

from __future__ import annotations

import argparse
import logging
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from src.capture import AssemblyAICapture, AssemblyAIAuthError, CaptureConfig
from src.config import load_config
from src.keyboard_input import lock_target_window, press_enter, type_text
from src.voice_commands import COMMAND_HELP, execute_command, handle_command, _FOCUS_LABELS, set_reconnect_callback
from src.voice_profile import profile_command, profile_hotkey

# V3 engine (transplanted from voice-bridge-v3, STEP 2). Persistence + health,
# plus the Stage 2 interpretation shadow. Neither has live authority: the
# shadow writes only to data/shadow-log and never touches dictation.
from src.capture_service import CaptureService as V3CaptureService
from src.capture_service import CaptureConfig as V3CaptureConfig
from src.capture_service import TranscriptRecord
from src.interpretation_shadow import InterpretationShadowPipeline

_MUTEX_NAME = "Global\\voice_bridge_single_instance"
_MUTEX_HANDLE = None

# Transcription corrections: (as the engine hears it, desired spelling).
# Applied to every finalized transcript before command handling / typing.
_TRANSCRIPTION_CORRECTIONS: tuple[tuple[str, str], ...] = (
    ("Myers-Holcomb", "Meyers-Holum"),
    ("Myers Holcomb", "Meyers-Holum"),
    ("Myers-Holum", "Meyers-Holum"),
    ("Lucci Lucci", "Luce"),
    ("Lucci", "Luce"),
    ("Lucy", "Luce"),
    ("lucci", "Luce"),
    ("lucy", "Luce"),
    ("Koda", "Coda"),
    ("koda", "Coda"),
    ("Talent", "Talon"),
    ("talent", "Talon"),
    ("Karado", "Corrado"),
    ("karado", "Corrado"),
    # GCE Frozen Seat Migration 2026-09-22: Vittorio / Nico pronunciations.
    ("Vitorio", "Vittorio"),
    ("vitorio", "Vittorio"),
    ("Niko", "Nico"),
    ("niko", "Nico"),
    ("nico", "Nico"),
    ("Thiago", "Chiave"),
    ("thiago", "Chiave"),
    ("Tiago", "Chiave"),
    ("tiago", "Chiave"),
)

# Self-reference translation (Don, 2026-09-07): "it's me" / standalone "me" ->
# "Don" when dictating. \b word-boundary keeps "me" inside longer words
# (theme/same/come/them/someone...) from being rewritten.
_SELF_REF_ITME = re.compile(r"\bit'?s\s+me\b", re.IGNORECASE)
_SELF_REF_ME = re.compile(r"\bme\b", re.IGNORECASE)

# Auto-macro thresholds (defaults; override via config.json
# auto_proofread_after / auto_concise_after. 0 disables a bound).
_AUTO_PROOFREAD_AFTER = 300
_AUTO_CONCISE_AFTER = 7000

# Named logger for the bridge process. Lifecycle events go through this, not
# print(), so they carry timestamps + level + component name (Don 2026-09-25).
logger = logging.getLogger("voicebridge")


def _log_file_path() -> Path:
    return Path("latest_logs") / "bridge.log"


def setup_logging() -> None:
    """Install a timestamped, named, file+console log sink.

    Without this the root logger has NO handler (verified 2026-09-25: the
    logging.basicConfig() calls in llm.py / screenshot.py sit behind
    ``__main__`` guards and never run), so every logger.info event — capture
    started, websocket closed, session terminated, pause, resume — is
    silently dropped and a dead pipeline is indistinguishable from a healthy
    one. Idempotent: safe to call more than once.
    """
    root = logging.getLogger()
    if any(getattr(h, "_voicebridge", False) for h in root.handlers):
        return
    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    try:
        log_path = _log_file_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        log_path = Path("bridge.log")

    # Under pythonw, _setup_stdio() already redirected sys.stderr into the log
    # file — adding a second FileHandler for the same path would double-write.
    try:
        existing = getattr(sys.stderr, "name", None)
        stderr_is_log = existing is not None and str(existing) == str(log_path)
    except Exception:
        stderr_is_log = False

    if not stderr_is_log:
        try:
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            file_handler.setFormatter(fmt)
            file_handler.setLevel(logging.INFO)
            setattr(file_handler, "_voicebridge", True)
            root.addHandler(file_handler)
        except Exception:
            pass

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(fmt)
    stream_handler.setLevel(logging.INFO)
    setattr(stream_handler, "_voicebridge", True)
    root.addHandler(stream_handler)
    root.setLevel(logging.INFO)


def acquire_lock() -> bool:
    """Return True if this process got the single-instance lock.

    Never fail-open: if the mutex cannot be created/queried, deny the start
    rather than risk two bridges streaming + typing (double billing / doubles).
    """
    global _MUTEX_HANDLE
    try:
        import ctypes
        from ctypes import wintypes
        k = ctypes.windll.kernel32
        CreateMutexW = ctypes.WINFUNCTYPE(
            wintypes.HANDLE, wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR,
            use_last_error=True,
        )(("CreateMutexW", k))
        _MUTEX_HANDLE = CreateMutexW(None, False, _MUTEX_NAME)
        already = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
        if already:
            release_lock()
            return False
        return bool(_MUTEX_HANDLE)
    except Exception:
        return False


def release_lock() -> None:
    global _MUTEX_HANDLE
    if not _MUTEX_HANDLE:
        return
    try:
        import ctypes
        from ctypes import wintypes
        k = ctypes.windll.kernel32
        k.ReleaseMutex.argtypes = [wintypes.HANDLE]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.ReleaseMutex(_MUTEX_HANDLE)
        k.CloseHandle(_MUTEX_HANDLE)
    except Exception:
        pass
    _MUTEX_HANDLE = None


class WakeWordBridge:
    """Wake-word gated voice dictation bridge (SLEEPING -> ARM -> type)."""

    SLEEPING = "sleeping"
    ARMED = "armed"

    def __init__(self, config_path: str = "config.json"):
        self.config = load_config(config_path)

        # AssemblyAI API key: config > env > .env
        self.assemblyai_api_key = self.config.get("assemblyai_api_key") or os.getenv("ASSEMBLYAI_API_KEY")
        if not self.assemblyai_api_key and Path(".env").exists():
            try:
                from dotenv import load_dotenv
                load_dotenv(".env", override=True)
                self.assemblyai_api_key = os.getenv("ASSEMBLYAI_API_KEY")
            except Exception:
                pass

        # Continuous mode: when True, dictation types into the focused window
        # with no wake-word gate (SLEEPING/ARMED bypassed). Toggle via the UI
        # "continuous" checkbox or the voice command "continuous mode".
        self.continuous = bool(self.config.get("continuous", False))
        self.paused = False  # continuous-mode pause ("sleep" / "wake up", Don 2026-09-25)

        # Wake-word gating state machine.
        self.state = self.SLEEPING
        self.wake_words: tuple[str, ...] = tuple(self.config.get("wake_words") or ())
        self._armed_until = 0.0
        self._armed_timeout = float(self.config.get("armed_timeout_seconds", 12.0))

        self.capture: AssemblyAICapture | None = None
        self._stopping = False
        # Reconnect backoff shared with the supervisor so the Reconnect button can
        # force an immediate attempt (resets backoff to the base interval).
        self._reconnect_backoff = float(self.config.get("supervisor_interval_seconds", 2.0))
        # Cumulative dictated characters since the last auto-macro reset.
        self._typed_chars = 0
        # Auto-macro thresholds from config (0 disables).
        self._auto_proofread_after = self.config.get("auto_proofread_after", _AUTO_PROOFREAD_AFTER)
        self._auto_concise_after = self.config.get("auto_concise_after", _AUTO_CONCISE_AFTER)

        # Finals handled in arrival order by a single dispatcher thread.
        self._final_queue: queue.Queue[str] = queue.Queue()
        self._dispatch_thread: threading.Thread | None = threading.Thread(
            target=self._dispatch_loop, daemon=True, name="vb-dispatch"
        )
        self._dispatch_thread.start()

        # UI handles (set in run(); None during self-test). Declared BEFORE the
        # V3 engine is built, because engine construction can report a fault
        # through the status line and that must not be an AttributeError.
        self.root = None
        self.status_label = None
        self.health_label = None
        # mute_btn is created in _build_ui(). Declared here so that any path
        # which reaches _sync_mute_button() before the window exists (headless
        # self-test, a partial UI build, a failed Tk init) degrades to "no
        # button to update" instead of raising AttributeError. Baseline only
        # ever set this inside _build_ui.
        self.mute_btn = None

        # ------------------------------------------------------------------
        # V3 ENGINE — persistence (G6) + health + Stage 2 shadow
        # ------------------------------------------------------------------
        # Ordering is a STRUCTURAL guarantee, not a convention: the durable
        # write happens in _engine_loop and only then is the final enqueued for
        # typing. So a typed character can never exist without its durable
        # transcript already on disk. That is the G6 invariant expressed as
        # code order, and it is the reason this is a second thread rather than
        # a call inside the dispatcher.
        self.v3_engine: V3CaptureService | None = None
        self.v3_shadow: InterpretationShadowPipeline | None = None
        self._shadow_queue: queue.Queue = queue.Queue()
        self._shadow_thread: threading.Thread | None = None
        self._turn_queue: queue.Queue[tuple[str, bool]] = queue.Queue()
        self._engine_thread: threading.Thread | None = threading.Thread(
            target=self._engine_loop, daemon=True, name="vb-engine"
        )
        self._engine_thread.start()
        self._init_v3_engine()

    # ------------------------------------------------------------------
    # V3 engine construction
    # ------------------------------------------------------------------
    def _init_v3_engine(self) -> None:
        """Build the V3 engine + shadow. Never fatal: a dead engine must not
        stop dictation, but it must be LOUD (STEP 3.D — observable silence is
        a fault, never quiet), so failure becomes a latched health fault and a
        visible status line, not a stack trace and not silence.
        """
        try:
            paths = self.config.get("paths") or {}
            shadow_dir = paths.get("shadow_log", "data/shadow-log")
            engine_cfg = V3CaptureConfig.from_shell_config(
                self.config, self.assemblyai_api_key or ""
            )
            self.v3_engine = V3CaptureService(engine_cfg)
            self.v3_engine.start()
            self.v3_engine.on_transcript = self._shadow_ingest
            self.v3_shadow = InterpretationShadowPipeline(
                shadow_log_dir=shadow_dir,
                model_version=str(
                    (self.config.get("v3") or {}).get("model_version", "gpt-4o-mini")
                ),
            )
            self._shadow_thread = threading.Thread(
                target=self._shadow_loop, daemon=True, name="vb-shadow"
            )
            self._shadow_thread.start()
            logger.info(
                "V3 engine live | transcripts=%s shadow=%s",
                engine_cfg.transcripts_dir, shadow_dir,
            )
        except Exception as e:
            logger.error("V3 engine FAILED to start: %s", e, exc_info=True)
            self._set_status(f"V3 ENGINE FAULT: {e}")
            if self.v3_engine is not None:
                self.v3_engine.health.mark_health_fault(f"engine init failed: {e}")

    # ------------------------------------------------------------------
    # V3 engine loop — durable transcript BEFORE the text can be typed
    # ------------------------------------------------------------------
    def _engine_loop(self) -> None:
        while not self._stopping:
            try:
                text, is_final = self._turn_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._persist_turn(text, is_final)
            except Exception as e:
                # A persistence failure must not silently drop the utterance.
                self._set_status(f"V3 persist error: {e}")
                logger.error("V3 engine turn failed: %s", e, exc_info=True)
                # Fail LOUD, and still deliver: the operator's words are worth
                # more than a clean disk, but the loss is on the status line.
                if is_final:
                    self._final_queue.put(text)

    def _persist_turn(self, text: str, is_final: bool) -> None:
        """One STT Turn frame -> durable-or-ephemeral, then hand off.

        SURGERY C: a partial is persisted as EPHEMERAL (nothing on disk). A
        final is persisted DURABLE, exactly once, and only after that write
        succeeds is the text handed to the typing dispatcher.
        """
        engine = self.v3_engine
        if engine is None:
            # Engine absent: still deliver the text. Typing must not depend on
            # the engine being healthy, and the status line says why.
            if is_final:
                self._final_queue.put(text)
            return

        record = engine.persist_transcript(text, is_partial=not is_final)
        engine.emit(record)  # -> shadow queue; failures are contained there

        if is_final:
            self._final_queue.put(record.raw_text)  # complete text, unmodified

    # ------------------------------------------------------------------
    # Stage 2 interpretation shadow — OFFLINE, no authority, no emission
    # ------------------------------------------------------------------
    def _shadow_ingest(self, record: TranscriptRecord) -> None:
        """Engine consumer hook. FINAL records only.

        The shadow interprets a finished utterance. A partial has no stable
        meaning, and shadowing a moving target would be noise, so partials are
        not queued. Nothing here can reach dictation: the return value is
        discarded, the shadow writes only to data/shadow-log, and there is no
        Stage 3/4/5 in this build.
        """
        if record.is_partial:
            return
        self._shadow_queue.put(record)

    def _shadow_loop(self) -> None:
        while not self._stopping:
            try:
                record = self._shadow_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if self.v3_shadow is not None:
                    self.v3_shadow.interpret(record.raw_text, record.event_id)
            except Exception as e:
                logger.error("interpretation shadow failed (%s): %s",
                             record.event_id, e, exc_info=True)

    def v3_shadow_stats(self) -> dict:
        """Verification surface for the shadow pipeline. Read-only."""
        if self.v3_shadow is None:
            return {"running": False}
        return {
            "running": bool(self._shadow_thread and self._shadow_thread.is_alive()),
            "model_version": self.v3_shadow.model_version,
            "shadow_log_dir": str(self.v3_shadow.shadow_log_dir),
            "queued": self._shadow_queue.qsize(),
        }

    def v3_health(self) -> tuple[bool, str]:
        """Combined engine + audio-path health for the status line (STEP 3.D)."""
        if self.v3_engine is None:
            return False, "V3 engine not initialised"
        return self.v3_engine.health_status()

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------
    def run(self):
        if not acquire_lock():
            print("[LOCK] Voice Bridge is already running. Not starting another.")
            try:
                release_lock()
            except Exception:
                pass
            os._exit(0)

        if not self.assemblyai_api_key:
            print("ERROR: no AssemblyAI API key. Set assemblyai_api_key in config.json")
            print("       or ASSEMBLYAI_API_KEY in .env / the environment.")
            release_lock()
            return

        # Single live path: continuous dictation into the focused window.
        # The wake-word state machine is dormant (legacy). Forces continuous
        # so a stale `continuous:false` in config.json cannot re-arm it.
        self.continuous = True

        logger.info(
            "VoiceBridge start: continuous=%s mic_device=%r sample_rate=%s "
            "channels=%s supervisor_interval=%ss",
            self.continuous,
            self.config.get("mic_device"),
            self.config.get("sample_rate", 16000),
            self.config.get("channels", 1),
            self.config.get("supervisor_interval_seconds", 2.0),
        )

        self._build_ui()
        set_reconnect_callback(self._reconnect_now)
        threading.Thread(target=self._supervisor, daemon=True).start()
        logger.info("supervisor thread started")

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        try:
            self.root.mainloop()
        finally:
            self._shutdown()

    def self_test(self) -> bool:
        """Headless check: continuous dictation + command routing. Returns bool."""
        import sys
        from unittest.mock import patch
        vb = sys.modules[type(self).__module__]
        typed_seen: list[str] = []
        cmds_seen: list[str] = []

        def fake_type(text, interval=0.01):
            typed_seen.append(text)

        def fake_exec(action):
            cmds_seen.append(action)

        orig_type, orig_exec = vb.type_text, vb.execute_command
        vb.type_text = fake_type
        vb.execute_command = fake_exec
        self.continuous = True  # single live path: continuous dictation
        self.paused = False

        checks: list[tuple[str, bool]] = []

        def chk(name, cond):
            checks.append((name, bool(cond)))
            print(f"  [{'PASS' if cond else 'FAIL'}] {name}")

        def reset():
            typed_seen.clear()
            cmds_seen.clear()

        try:
            # 1) Continuous: plain speech types verbatim.
            reset()
            self.paused = False
            self._handle_final("the quick brown fox jumps over the lazy dog")
            chk("continuous dictation types", typed_seen == ["the quick brown fox jumps over the lazy dog "])

            # 2) Continuous: command executes, not typed.
            reset()
            self.paused = False
            self._handle_final("copy that")
            chk("command executes, not typed", cmds_seen == ["copy"] and typed_seen == [])

            # 3) 'sleep' pauses; subsequent speech is ignored (Don 2026-09-25).
            reset()
            self.paused = False
            self._handle_final("sleep")
            self._handle_final("this should not type")
            chk("'sleep' pauses", self.paused is True and typed_seen == [])

            # 4) 'wake up' resumes dictation (Don 2026-09-25).
            reset()
            self.paused = True
            self._handle_final("wake up")
            self._handle_final("resume dictation now")
            chk("'wake up' resumes", self.paused is False
                and typed_seen == ["resume dictation now "])

            # 5) 'quit' schedules a close, does not type.
            reset()
            self.paused = False
            with patch.object(self, "_schedule_close") as mock_close:
                self._handle_final("quit")
                mock_close.assert_called_once()
            chk("quit closes", cmds_seen == [] and typed_seen == [])

            # 6) Substring safety: 'apex' types as text, not a command.
            reset()
            self.paused = False
            self._handle_final("apex predator results")
            chk("substring apex types as text", typed_seen == ["apex predator results "])

            # 7) "stop listening" / "start listening" are REMOVED from the
            #    command set (Don 2026-09-25) — both type as dictation, and
            #    neither pauses nor resumes the bridge.
            reset()
            self.paused = False
            self._handle_final("stop listening")
            self._handle_final("start listening")
            chk("'stop/start listening' type as dictation", self.paused is False
                and typed_seen == ["stop listening ", "start listening "])
            reset()
            self.paused = False
            self._handle_final("sleep")
            self._handle_final("this should type")
            chk("paused by 'sleep' stays paused", self.paused is True
                and typed_seen == [])

            # 8) 'wake up' resumes; while paused every other utterance is
            #    ignored (no fuzzy resume path).
            reset()
            self.paused = True
            self._handle_final("wake up")
            self._handle_final("resume dictation now")
            chk("'wake up' resumes", self.paused is False
                and typed_seen == ["resume dictation now "])
            reset()
            self.paused = True
            self._handle_final("start listening")
            self._handle_final("should still be ignored")
            chk("paused bridge ignores dictation", self.paused is True
                and typed_seen == [])

            # 9) Leading 'sleep' in dictation TYPES — no false pause.
            reset()
            self.paused = False
            self._handle_final("sleep is important")
            chk("sleep is important types", self.paused is False
                and typed_seen == ["sleep is important "])

            # 10) Leading 'wake up' in dictation TYPES — no false resume, and a
            #     paused bridge stays paused instead of resuming.
            reset()
            self.paused = False
            self._handle_final("wake up and go")
            chk("wake up and go types", self.paused is False
                and typed_seen == ["wake up and go "])
            reset()
            self.paused = True
            self._handle_final("wake up and go")
            chk("wake up and go does not resume", self.paused is True
                and typed_seen == [])

            # 11) Exact single-word commands still fire (not lost by the new
            #     exact-utterance rule).
            reset()
            self.paused = False
            self._handle_final("right")
            self._handle_final("copy")
            chk("exact single-word commands fire", cmds_seen == ["right", "copy"]
                and typed_seen == [])

            # 12) A single-word command at the START of dictation types instead
            #     of firing ("Right, if you need me" collision — fixed).
            reset()
            self.paused = False
            self._handle_final("right, this is normal")
            chk("leading 'right' in dictation types", cmds_seen == []
                and typed_seen == ["right, this is normal "])

            # 13) Command words appearing inside longer dictation type as text.
            reset()
            self.paused = False
            for utt in ("save the document", "copy the notes",
                        "send the file", "who is calling"):
                self._handle_final(utt)
            chk("single word in dictation types (save/copy/send/who)",
                cmds_seen == [] and typed_seen ==
                ["save the document ", "copy the notes ", "send the file ",
                 "who is calling "])

            # 14) Don 2026-09-25 — canonical pause/resume language. Exact
            #     whole-utterance match only, no prefix matching in either
            #     direction: bare/punctuated command fires, any longer
            #     sentence stays dictation.
            for utt in ("Sleep.", "sleep"):
                reset()
                self.paused = False
                self._handle_final(utt)
                chk(f"{utt!r} -> pause", self.paused is True
                    and typed_seen == [] and cmds_seen == [])
            for utt in ("Wake up.", "wake up"):
                reset()
                self.paused = True
                self._handle_final(utt)
                chk(f"{utt!r} -> resume", self.paused is False
                    and typed_seen == [] and cmds_seen == [])
            for utt in ("I need to sleep.", "Sleep is important.",
                        "I need to wake up tomorrow.",
                        "Wake up the computer tomorrow.",
                        "stop listening", "start listening"):
                reset()
                self.paused = False
                self._handle_final(utt)
                chk(f"{utt!r} -> dictation", self.paused is False
                    and typed_seen == [utt + " "] and cmds_seen == [])
        finally:
            vb.type_text = orig_type
            vb.execute_command = orig_exec

        passed = all(ok for _, ok in checks)
        print(f"\nSELF-TEST: {sum(1 for _, ok in checks if ok)}/{len(checks)} checks passed -> "
              f"{'OK' if passed else 'FAILED'}")
        return passed

    # ------------------------------------------------------------------
    # Transcript handling (continuous dictation)
    # ------------------------------------------------------------------
    def on_transcript(self, text: str, is_final: bool):
        """Called from the AssemblyAI recv thread.

        V3: this thread now does the LEAST possible work. It hands the frame to
        the engine queue and returns. The durable write, the shadow hand-off and
        the typing all happen on other threads, so a slow disk can never stall
        the audio recv loop (which would show up as dropped audio), and the
        persist-before-type ordering is preserved structurally.
        """
        if not text.strip():
            return
        if not is_final:
            # SURGERY C: ephemeral. This is a display preview only — it is
            # never written to disk by anything downstream of here.
            self._set_status(f"♪ {text[:40]}")
            self._turn_queue.put((text, False))
            return
        self._turn_queue.put((text, True))

    def _dispatch_loop(self):
        while not self._stopping:
            try:
                text = self._final_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            self._log_utterance(text)
            self._safe_handle(text)

    def _log_utterance(self, text: str):
        # Disk write lives on the dispatcher thread, never the recv thread.
        try:
            from src.intent import log_utterance
            log_utterance(text)
        except Exception:
            pass

    def _safe_handle(self, text: str):
        try:
            self._handle_final(text)
        except Exception as e:
            self._set_status(f"dispatch error: {e}")

    def _maybe_auto_macro(self):
        """Auto select-all + proofread/concise when dictated length crosses a bound."""
        if self._auto_proofread_after <= 0:
            return
        n = self._typed_chars
        if self._auto_concise_after > 0 and n >= self._auto_concise_after:
            self._set_status(f"auto ({n} chars): proofread -> concise -> send")
            for cmd in ("macro_proofread", "macro_concise", "enter"):
                try:
                    execute_command(cmd)
                except Exception as e:
                    self._set_status(f"auto command error: {e}")
                    return
            self._typed_chars = 0
            return
        if n >= self._auto_proofread_after:
            self._set_status(f"auto ({n} chars): proofread")
            try:
                execute_command("macro_proofread")
            except Exception as e:
                self._set_status(f"auto command error: {e}")
                return
            self._typed_chars = 0

    def _refresh_arm(self):
        self._armed_until = time.time() + self._armed_timeout

    def _set_state(self, state: str):
        self.state = state
        if state == self.ARMED:
            self._refresh_arm()

    def _is_armed(self) -> bool:
        return self.state == self.ARMED and time.time() <= self._armed_until

    def _find_wake_word(self, text: str) -> str | None:
        """Return the wake word matched at the start of ``text`` (longest first).

        Word-boundary aware. A bare `startswith` would strip "keel" out of
        "keelbase", "keelson" and any proper noun that happens to begin with
        the letters — the STT emits those often enough that a dictation could
        be silently mangled. The match must end at a word boundary: end of
        string, whitespace, or punctuation.
        """
        low = text.lower()
        best: str | None = None
        for ww in self.wake_words:
            if not ww:
                continue
            w = ww.lower()
            if not low.startswith(w):
                continue
            tail = low[len(w):]
            if tail and not (tail[0].isspace() or tail[0] in ".,;:!?'\"-—…"):
                continue  # "keelbase" is not the wake word
            if best is None or len(ww) > len(best):
                best = ww
        return best

    def _handle_final(self, text: str):
        """Route one finalized transcript through the wake-word state machine."""
        text = (text or "").strip()
        if not text:
            return

        # Continuous mode: type into the focused window, no wake-word gate.
        # Session commands still work (stop/start/quit); everything else types.
        if self.continuous:
            # ------------------------------------------------------------------
            # WAKE WORD IN THE LIVE PATH (Gate P amendment, 2026-10-01).
            # ------------------------------------------------------------------
            # `run()` forces continuous=True, which meant the wake-word gate
            # below was unreachable: saying "hey keel" TYPED the words "hey
            # keel" into the focused window and never armed anything. The wake
            # word is a Sec. 2 required flow ("wake word -> activate
            # listening"), so this is a parity failure, not a legacy quirk to
            # be left alone.
            #
            # Now: a leading wake word is consumed. Bare wake word -> arm and
            # type nothing. Wake word + payload -> the payload is dispatched and
            # the wake word is not typed. An utterance that does not start with
            # a wake word is completely untouched, so no other flow changes.
            ww = self._find_wake_word(text)
            if ww is not None:
                payload = text[len(ww):].strip()
                self._set_state(self.ARMED)
                if not payload:
                    self._set_status(f"● {ww} — listening, speak now")
                    logger.info("ARMED by wake word | word=%r", ww)
                    return
                text = payload
                logger.info("wake word stripped | word=%r payload=%r", ww, payload)
                self._refresh_arm()

            cmd = handle_command(text)
            if cmd == "quit":
                self._set_status("quitting...")
                self._schedule_close()
                return
            if cmd in ("pause",):
                self.paused = True
                self._set_status("○ paused — say wake up")
                logger.info("PAUSED by command | utterance=%r", text)
                return
            if cmd in ("resume",):
                self.paused = False
                self._set_status("● listening")
                logger.info("RESUMED by command | utterance=%r", text)
                return
            if cmd == "help":
                self._set_status("help printed")
                print(COMMAND_HELP)
                return
            if self.paused:
                self._set_status(f"paused · ignored: {text[:24]}")
                return
            lock_target_window()  # type into the window the user has focused
            self._dispatch(text)
            return

        # 1) Wake word present -> arm (strip wake word, dispatch payload if any).
        ww = self._find_wake_word(text)
        if ww is not None:
            self._set_state(self.ARMED)
            lock_target_window()  # remember the window the user had focused
            payload = text[len(ww):].strip()
            if payload:
                self._dispatch(payload)
            else:
                self._set_status("● listening — speak now")
            return

        # 2) Not armed -> ignore ambient speech entirely.
        if not self._is_armed():
            return

        # 3) Armed -> session cmd / quick cmd / type.
        self._refresh_arm()
        self._dispatch(text)

    def _dispatch(self, text: str):
        # Transcription corrections — spoken phrase -> desired spelling.
        # "Myers-Holcomb" (how the engine hears it) -> "Meyers-Holum".
        for _bad, _good in _TRANSCRIPTION_CORRECTIONS:
            if _bad in text:
                text = text.replace(_bad, _good)
        # Self-reference translation (Don, 2026-09-07): when the operator says
        # "it's me" or a standalone "me" while dictating, type "Don" instead.
        # Word-boundary-safe: never rewrites "me" inside another word
        # (theme/same/come/them...) or inside a voiced command phrase.
        if not text.isspace():
            text = _SELF_REF_ITME.sub("Don", text)
            text = _SELF_REF_ME.sub("Don", text)
        cmd = handle_command(text)
        if cmd == "quit":
            self._set_status("quitting...")
            self._schedule_close()
            return
        if cmd in ("pause",):
            self._set_state(self.SLEEPING)
            self._set_status("○ sleeping — say wake word")
            return
        if cmd in ("resume",):
            self._set_state(self.ARMED)
            self._set_status("● listening")
            return
        if cmd == "help":
            self._set_status("help printed")
            print(COMMAND_HELP)
            return

        if cmd is not None:
            try:
                ok = execute_command(cmd)
                if ok is False:
                    if cmd.startswith("window_"):
                        self._set_status(f"no window {cmd.split('_', 1)[1]}")
                    elif cmd.startswith("terminal_"):
                        self._set_status(f"no terminal {cmd.split('_', 1)[1]}")
                    elif cmd.startswith("screen_"):
                        self._set_status(f"no screen {cmd.split('_', 1)[1]}")
                    else:
                        self._set_status(f"no window titled {_FOCUS_LABELS.get(cmd, cmd)}")
                elif isinstance(ok, str):
                    self._set_status(ok[:90])
                else:
                    self._set_status(f"command: {cmd}")
            except Exception as e:
                self._set_status(f"command error: {e}")
            return

        # Voice profile: a spoken phrase maps to a tool-specific terminal
        # command. Slash commands are typed verbatim; keybind entries (e.g.
        # opencode session_fork) are fired as hotkeys. Do this before falling
        # through to plain dictation.
        slash = profile_command(text)
        if slash:
            lock_target_window()
            type_text(slash, interval=0.01)
            self._set_status(f"profile: {slash}")
            return
        hotkey = profile_hotkey(text)
        if hotkey:
            lock_target_window()
            try:
                import pyautogui
                pyautogui.FAILSAFE = False
                pyautogui.hotkey(*hotkey["keys"])
            except Exception:
                pass
            self._set_status(f"profile: {hotkey['key']}")
            return

        try:
            type_text(text + " ", interval=0.01)
            self._set_status(f"typed: {text[:40]}")
            self._typed_chars += len(text)
            self._maybe_auto_macro()
        except Exception as e:
            self._set_status(f"type error: {e}")

    # ------------------------------------------------------------------
    # Always-on AssemblyAI capture + supervisor
    # ------------------------------------------------------------------
    def _build_capture(self) -> AssemblyAICapture:
        device_index = self._resolve_mic_device(self.config.get("mic_device"))
        logger.info(
            "building capture | mic_device=%r device_index=%r speech_model=%r "
            "sample_rate=%s",
            self.config.get("mic_device"), device_index,
            self.config.get("speech_model", "universal-3-5-pro"),
            self.config.get("sample_rate", 16000),
        )
        cfg = CaptureConfig(
            api_key=self.assemblyai_api_key,
            device_index=device_index,
            speech_model=self.config.get("speech_model", "universal-3-5-pro"),
            sample_rate=self.config.get("sample_rate", 16000),
            channels=self.config.get("channels", 1),
            keyterms=tuple(self.config.get("keyterms") or ()),
        )
        cap = AssemblyAICapture(cfg)
        cap.on_transcript = self.on_transcript
        return cap

    def _resolve_mic_device(self, value) -> int | None:
        if value is None or value == "default":
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        self._set_status(f"WARNING: invalid mic_device {value!r} — using default")
        return None

    def _ensure_dispatcher(self) -> None:
        """Component liveness: restart the dispatcher if it ever dies.

        It is the single consumer of ``_final_queue``; if it exits, every
        final transcript after that point is silently enqueued and never
        typed, and nothing else in the system would notice.
        """
        if self._stopping:
            return
        thread = self._dispatch_thread
        if thread is not None and thread.is_alive():
            return
        logger.error("dispatcher thread dead — restarting")
        thread = threading.Thread(
            target=self._dispatch_loop, daemon=True, name="vb-dispatch"
        )
        thread.start()
        self._dispatch_thread = thread

    def _ensure_engine_thread(self) -> None:
        """Same liveness argument as the dispatcher, for the V3 engine thread.

        `_engine_loop` is the single consumer of `_turn_queue` AND the only
        thing standing between a spoken utterance and a durable transcript. If
        it dies, finals pile up in the queue and nothing is typed and nothing is
        written — the failure is total and silent. So it is restarted here, and
        the restart is logged, not swallowed.
        """
        if self._stopping:
            return
        thread = self._engine_thread
        if thread is not None and thread.is_alive():
            return
        logger.error("V3 engine thread dead — restarting "
                     "(durable transcripts would otherwise stop)")
        thread = threading.Thread(
            target=self._engine_loop, daemon=True, name="vb-engine"
        )
        thread.start()
        self._engine_thread = thread

    def _supervisor(self):
        interval = float(self.config.get("supervisor_interval_seconds", 2.0))
        while not self._stopping:
            try:
                self._ensure_dispatcher()
                self._ensure_engine_thread()
                # Health gate: `is_running()` alone only proves the intent to
                # run. The audio device, the websocket and the send/recv
                # coroutines can each die while `_running` stays True.
                dead_reason: str | None = None
                if self.capture is None:
                    dead_reason = "no capture"
                elif not self.capture.is_running():
                    dead_reason = "capture stopped"
                else:
                    healthy, why = self.capture.health()
                    if not healthy:
                        dead_reason = why
                    elif self.v3_engine is not None:
                        # Heartbeat bridge (SURGERY D): the engine's silence
                        # timer can only be honest if something tells it the
                        # device is still delivering. A healthy audio path is
                        # that signal. Silence while unhealthy never reaches
                        # here, so it can never masquerade as a live mic.
                        self.v3_engine.health.record_audio()

                self._refresh_health_line(dead_reason)

                if dead_reason is not None:
                    # SURGERY D: the audio path's own verdict is latched into
                    # the V3 engine so the engine reports the fault instead of
                    # reporting "healthy" off a timer it cannot see.
                    if self.v3_engine is not None:
                        self.v3_engine.health.adopt_external_health(
                            False, f"audio path: {dead_reason}"
                        )
                    if self.capture is not None:
                        auth_err = self.capture.auth_error
                        logger.warning(
                            "capture unhealthy — recovery attempt | reason=%s",
                            dead_reason,
                        )
                        if dead_reason != "no capture" and dead_reason != "capture stopped":
                            self._set_status(f"capture degraded: {dead_reason} — reconnecting...")
                        try:
                            self.capture.stop()
                        except Exception:
                            pass
                        self.capture = None
                        if auth_err is not None:
                            self._set_status(
                                f"AUTH/BILLING ERROR: AssemblyAI {auth_err.status} "
                                f"— {auth_err} — check key/credits"
                            )
                            logger.error(
                                "recovery held: auth/billing error %s",
                                auth_err.status,
                            )
                            self._reconnect_backoff = min(
                                120.0, max(30.0, self._reconnect_backoff * 2)
                            )
                            time.sleep(self._reconnect_backoff)
                            continue
                    self._set_status("connecting to AssemblyAI...")
                    cap = self._build_capture()
                    try:
                        cap.start()
                        self.capture = cap
                        self._sync_mute_button()
                        if cap.is_auth_error():
                            self._set_status(
                                f"AUTH/BILLING ERROR: AssemblyAI "
                                f"{cap.auth_error.status} — {cap.auth_error} — "
                                "check key/credits"
                            )
                            logger.error(
                                "recovery failed: auth/billing error %s",
                                cap.auth_error.status,
                            )
                            self._reconnect_backoff = min(
                                120.0, max(30.0, self._reconnect_backoff * 2)
                            )
                        else:
                            self._reconnect_backoff = interval
                            # A rebuilt session clears the latched fault: the
                            # fault was real, and it is now resolved. Silence
                            # clears on its own; a connection fault does not.
                            if self.v3_engine is not None:
                                self.v3_engine.health.clear_fault()
                            self._set_status("● listening — speak now")
                            logger.info(
                                "recovery succeeded — capture running | "
                                "backoff=%.1fs", interval,
                            )
                    except AssemblyAIAuthError as e:
                        self._set_status(
                            f"AUTH/BILLING ERROR: AssemblyAI {e.status} — {e} — "
                            "check key/credits"
                        )
                        logger.error(
                            "recovery failed: auth/billing error %s", e.status,
                        )
                        self._reconnect_backoff = min(
                            120.0, max(30.0, self._reconnect_backoff * 2)
                        )
                    except Exception as e:
                        self._set_status(f"capture start error: {e}")
                        logger.error(
                            "recovery failed: capture start error", exc_info=True,
                        )
                        self._reconnect_backoff = min(30.0, self._reconnect_backoff * 2)
            except Exception as e:
                self._set_status(f"supervisor error: {e}")
                logger.error("supervisor loop error", exc_info=True)
            time.sleep(self._reconnect_backoff)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        self.root = tk.Tk()
        self.root.title("VoiceBridge")
        # REPAIR 2026-10-02 (Nico): 480x640 -> 720x680. The handoff queue is the
        # main content of this window and its seven columns need ~620px; at 480
        # the right-hand columns were off-screen. Everything else in the layout
        # is unchanged. minsize keeps the queue reachable if the window is
        # dragged narrow (the tree also carries a horizontal scrollbar).
        self.root.geometry("720x680")
        self.root.minsize(560, 480)
        self.root.attributes("-topmost", True)

        ttk.Label(self.root, text="VoiceBridge", font=("Arial", 14)).pack(pady=(10, 2))
        self.status_label = ttk.Label(self.root, text="starting...", font=("Arial", 10))
        self.status_label.pack(pady=(6, 2), fill="x", padx=10)
        # V3 SURGERY D: engine health (STT connection + capture loop) in the
        # status area. One added line; nothing else in the layout moves.
        self.health_label = ttk.Label(self.root, text="HEALTH starting...",
                                      font=("Arial", 8))
        self.health_label.pack(pady=(0, 2), fill="x", padx=10)

        btns = ttk.Frame(self.root)
        btns.pack(pady=4)
        ttk.Label(btns, text="MODE: continuous", font=("Arial", 9, "bold")).pack(pady=2)
        self.mute_btn = ttk.Button(btns, text="MIC: ON", command=self._toggle_mute)
        self.mute_btn.pack(side="left", padx=4)
        ttk.Button(btns, text="Reconnect", command=self._reconnect_now).pack(padx=4)
        ttk.Button(btns, text="Quit", command=self._on_close).pack(padx=4)

        # Handoff review queue — Don/Coda review surface, READ-ONLY.
        # Never writes a handoff record; a broken panel must not stop dictation.
        self.queue_panel = None
        try:
            from src.queue_panel import QueuePanel
            self.queue_panel = QueuePanel(self.root, self.config)
            self.queue_panel.pack(fill="both", expand=True, padx=8, pady=(2, 8))
        except Exception as e:
            import traceback
            traceback.print_exc()
            ttk.Label(self.root, text=f"queue panel unavailable: {e}",
                      foreground="#b91c1c").pack(pady=4)

    def _toggle_mute(self):
        if self.capture is None:
            self._set_status("capture not started yet")
            return
        muted = not self.capture.is_muted()
        self.capture.set_muted(muted)
        self._set_status("MIC MUTED" if muted else "MIC ON — listening")
        self._sync_mute_button()

    def _sync_mute_button(self):
        if self.capture is None or self.mute_btn is None:
            return
        muted = self.capture.is_muted()
        text = "MIC: MUTED" if muted else "MIC: ON"

        def _apply():
            try:
                self.mute_btn.config(text=text)
            except Exception:
                pass

        if self.root is not None:
            self.root.after(0, _apply)
        else:
            _apply()

    def _refresh_health_line(self, dead_reason: str | None = None):
        """SURGERY D — render engine + audio-path health into the status area.

        Minimal UI change, per STEP 3.D: one extra label under the existing
        status line. The panel layout Don knows is otherwise untouched.

        The rule this enforces: a dead pipeline is never presented as a quiet
        one. A fault is named in the window, not just in the log file, because
        the log file is exactly what nobody was reading when the baseline
        watcher died silently for four days.
        """
        if self.root is None or self.health_label is None:
            return
        engine_ok, engine_why = self.v3_health()
        cap_ok, cap_why = (False, "no capture")
        if self.capture is not None:
            cap_ok, cap_why = self.capture.health()
        ok = engine_ok and cap_ok and dead_reason is None
        if ok:
            text = f"HEALTH ok · stt {engine_why} · capture {cap_why}"
            color = "#166534"
        else:
            detail = dead_reason or (cap_why if not cap_ok else engine_why)
            text = f"HEALTH FAULT · {detail}"
            color = "#b91c1c"

        def _apply():
            try:
                self.health_label.config(text=text[:100], foreground=color)
            except Exception:
                pass

        try:
            self.root.after(0, _apply)
        except Exception:
            pass

    def _set_status(self, message: str):
        msg = str(message)
        if self.root is not None and self.status_label is not None:
            try:
                self.root.after(0, lambda: self.status_label.config(text=msg[:90]))
            except Exception:
                pass
        try:
            import sys as _sys
            if _sys.stdout is not None:
                print(msg)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    def _schedule_close(self):
        if self.root is not None:
            try:
                self.root.after(0, self._on_close)
            except Exception:
                self._on_close()
        else:
            self._stopping = True

    def _reconnect_now(self):
        """Force an immediate reconnect attempt (button-triggered).

        Stops the current capture (if any), clears it, and resets the supervisor's
        reconnect backoff to the base interval so the supervisor reconnects on its
        next pass instead of waiting out an existing backoff.
        """
        self._set_status("reconnect requested — reconnecting...")
        logger.info("manual reconnect requested — stopping current capture")
        if self.capture is not None:
            try:
                self.capture.stop()
            except Exception:
                pass
            self.capture = None
        self._reconnect_backoff = float(self.config.get("supervisor_interval_seconds", 2.0))

    def _on_close(self):
        self._stopping = True
        logger.info("close requested — shutting down")
        if self.capture is not None:
            try:
                self.capture.stop()
            except Exception:
                pass
            self.capture = None
        if self.root is not None:
            try:
                self.root.destroy()
            except Exception:
                pass

    def _shutdown(self):
        self._stopping = True
        logger.info("shutdown")
        if self.capture is not None:
            try:
                self.capture.stop()
            except Exception:
                pass
            self.capture = None
        release_lock()


VoiceBridge = WakeWordBridge  # backward-compat alias


def _setup_stdio() -> None:
    """Make stdout/stderr safe under pythonw (no console) and force UTF-8."""
    import sys
    log_path = Path("latest_logs") / "bridge.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        log_path = Path("bridge.log")
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            try:
                f = open(log_path, "a", encoding="utf-8", buffering=1)
                setattr(sys, name, f)
            except Exception:
                pass
        else:
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def main(argv: list[str] | None = None) -> int:
    _setup_stdio()
    setup_logging()
    parser = argparse.ArgumentParser(description="Voice Bridge (continuous dictation, AssemblyAI)")
    parser.add_argument("--config", default="config.json", help="path to config.json")
    parser.add_argument("--self-test", action="store_true", help="run headless check and exit")
    args = parser.parse_args(argv)

    bridge = WakeWordBridge(config_path=args.config)
    if args.self_test:
        ok = bridge.self_test()
        return 0 if ok else 1
    bridge.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())