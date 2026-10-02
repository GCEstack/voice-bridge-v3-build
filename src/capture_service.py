#!/usr/bin/env python3
"""
capture_service.py — V3 Engine: full-fidelity transcript persistence (G6)

TRANSPLANTED from `voice-bridge-v3\\src\\capture_service.py` (V-GATE 1 salvage)
into the VoiceBridge V3 integrated build on 2026-10-01.

WHAT WAS TRANSPLANTED
---------------------
  * `TranscriptRecord` / `CaptureConfig` / `CaptureService` names + shapes
  * `CaptureService.persist_transcript(text, is_partial, duration)` — the exact
    signature the carried-over G6 suite calls
  * `AudioRetentionManager` — 7-day rolling audio delete (D-V3-2)
  * `CaptureHealth` — silence-is-a-fault + explicit fault latch
  * `on_transcript(record)` consumer hook (the shadow pipeline's only entry)

G6 INVARIANT (binding; unchanged from the salvage)
--------------------------------------------------
  * The COMPLETE STT transcript is persisted BEFORE any normalization, intent
    classification, summarization, queue projection, UI shortening, or ANY
    lossy transform.
  * UI/display previews MAY shorten. Durable source evidence NEVER shortens.
  * Any component that receives full text and persists less is a DEFECT.

SURGERY POINT C — DURABILITY CONTRACT (changed from the salvage, by order)
-------------------------------------------------------------------------
The salvage persisted EVERY AssemblyAI Turn frame, partials included, into
`data/transcripts/<uuid>.json` — one file per Turn frame, and
`self._current_event_id` was declared but never assigned, so every frame also
minted a fresh uuid. One spoken utterance therefore produced many durable
files, most of them superseded milliseconds later.

V3 SPEC (STEP 3.C — "ephemeral partials, exactly ONE final durable transcript
per utterance"):

    is_partial=True   -> EPHEMERAL. A record is returned to in-process
                         consumers (UI preview, shadow) and NOTHING is written
                         to disk.
    is_partial=False  -> DURABLE. Exactly one file per utterance, written from
                         the full unmodified text.

This is the only behavioural change to the transplanted component. It makes the
salvage's durable corpus trustworthy: one utterance, one durable artifact.

SURGERY POINT D — HEALTH (changed from the salvage, by order)
-------------------------------------------------------------
The salvage's `CaptureHealth` only observed its own mic callback, because the
salvage owned the audio path. In the integrated build the mature shell loop
(`src/capture.py`) owns the mic/WebSocket, so the engine's silence timer would
be blind to real device loss.

V3 therefore adds:
  * `adopt_external_health(healthy, reason)` — the shell's own `health()`
    verdict is LATCHED, so a fault the mature loop already detected (dead recv
    loop, closed websocket, missing audio heartbeat) is never lost.
  * Latched faults do NOT self-clear on their own. Silence clears, because
    silence is the normal VAD-gated idle state; a connection fault does not,
    because the fault is real until the session is rebuilt.

REJECTED ALTERNATIVE (recorded so it is not re-litigated)
--------------------------------------------------------
The transplant order names `capture_service.py` as the "full-fidelity STT
capture (AssemblyAI v3 WebSocket)". Transcribing that literally — making this
module own the WebSocket and mic — was considered and REJECTED at the
implementation level, because it is a Gate P regression, not a Gate C win:

  * the salvage loop has no auth/billing classification, so a 402 "insufficient
    funds" frame would be retried forever while the UI read "listening"
    (inventory item: AssemblyAI v3 WebSocket STT / reconnect on drop);
  * it has no VAD silence gate (inventory item: VAD gate);
  * it never sends Terminate, so billed sessions run to the 3-hour server
    auto-close (inventory item: WebSocket drop handling);
  * it has no keyterms_prompt preload and no mic mute (inventory items:
    wake words, Mic toggle);
  * it has no ForceEndpoint finalisation, so the last utterance before Quit
    is silently dropped.

The engine's actual value to V3 is the G6 persistence + health contract, not a
second, weaker copy of the audio path. So this module is the PERSISTENCE +
HEALTH layer and `src/capture.py` remains the single audio path. The transplant
is complete; the audio path is not duplicated. [PROPOSED] — labelled because
this is a reading of STEP 2/STEP 3, not a verbatim instruction.

SCOPE LOCK (V-GATE 1, unchanged)
--------------------------------
Live capture IS in scope. This module holds NO interpretation authority, NO
reference/policy authority and NO emission authority. It writes transcripts and
health. Nothing else. No Stage 3/4/5.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("v3.capture")

# Hard ceiling on a single durable transcript. Not a truncation bound: a longer
# text is still persisted in full and this counter is raised. It exists so an
# unbounded utterance is visible rather than silent.
LENGTH_WARN_CHARS = 4000


@dataclass
class TranscriptRecord:
    """One STT turn. `raw_text` is the COMPLETE, unmodified STT output."""

    event_id: str
    timestamp: str
    raw_text: str
    audio_path: Optional[str] = None
    duration_seconds: Optional[float] = None
    stt_provider: str = "assemblyai"
    stt_model: str = "universal-3-5-pro"
    is_partial: bool = False
    is_durable: bool = True
    chars: int = 0

    @property
    def is_final(self) -> bool:
        return not self.is_partial


@dataclass
class CaptureConfig:
    """Engine configuration. Distinct from src.capture.CaptureConfig (audio)."""

    api_key: str
    transcripts_dir: str = "data/transcripts"
    audio_dir: str = "data/audio"
    device_index: Optional[int] = None
    speech_model: str = "universal-3-5-pro"
    sample_rate: int = 16000
    channels: int = 1
    chunk_size: int = 1600
    vad_threshold: float = 500.0
    vad_silence_seconds: float = 3.0
    audio_retention_days: int = 7
    silence_threshold_seconds: int = 10
    heartbeat_interval_seconds: int = 30
    keyterms: tuple = ()

    @classmethod
    def from_shell_config(cls, shell_config: dict, api_key: str) -> "CaptureConfig":
        """Build the engine config from the shell's merged config.json.

        One config surface (STEP 2: "config merged into the integration tree's
        config.json"). The shell's VAD / keyterms / device / model keys are
        read here so there is exactly one place a value is written down.
        """
        vb3 = (shell_config or {}).get("v3", {}) or {}
        paths = (shell_config or {}).get("paths", {}) or {}
        health = (shell_config or {}).get("capture_health", {}) or {}
        retention = (shell_config or {}).get("audio_retention", {}) or {}
        return cls(
            api_key=api_key,
            transcripts_dir=paths.get("transcripts", "data/transcripts"),
            audio_dir=paths.get("audio", "data/audio"),
            device_index=shell_config.get("mic_device"),
            speech_model=shell_config.get("speech_model", "universal-3-5-pro"),
            sample_rate=int(shell_config.get("sample_rate", 16000)),
            channels=int(shell_config.get("channels", 1)),
            vad_threshold=float(shell_config.get("vad_threshold", 500.0)),
            vad_silence_seconds=float(shell_config.get("vad_silence_seconds", 3.0)),
            audio_retention_days=int(retention.get("retention_days", 7)),
            silence_threshold_seconds=int(
                health.get("silence_threshold_seconds", 10)
            ),
            heartbeat_interval_seconds=int(
                health.get("heartbeat_interval_seconds", 30)
            ),
            keyterms=tuple(shell_config.get("keyterms") or ()),
        )


class AudioRetentionManager:
    """7-day rolling local retention for raw audio (D-V3-2).

    Deletes AUDIO ONLY. Never transcripts, never events, never provenance.
    """

    def __init__(self, audio_dir: str, retention_days: int):
        self.audio_dir = Path(audio_dir)
        self.retention_days = retention_days
        self.audio_dir.mkdir(parents=True, exist_ok=True)

    def cleanup_old_audio(self) -> int:
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        removed = 0
        for f in self.audio_dir.glob("*.wav"):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime < cutoff:
                    f.unlink()
                    removed += 1
            except Exception as e:  # a locked file must not abort the sweep
                logger.warning("audio retention: could not clean %s: %s", f, e)
        if removed:
            logger.info("audio retention: removed %d file(s) older than %d day(s)",
                        removed, self.retention_days)
        return removed


class CaptureHealth:
    """Silence-is-a-fault + an explicit, latched fault channel.

    `check()` returns (healthy, reason). Silence clears on its own (the VAD gate
    means silence is the normal idle state and the mic is still delivering
    blocks). A fault latched through `mark_health_fault()` or
    `adopt_external_health(False, ...)` does NOT clear on its own — it is real
    until the session is rebuilt, which is the whole point of "observable
    silence is a fault, never quiet".
    """

    def __init__(self, silence_threshold_seconds: int, heartbeat_interval: int = 30):
        self.silence_threshold_seconds = max(1, int(silence_threshold_seconds))
        self.heartbeat_interval = int(heartbeat_interval)
        self._last_audio_time: float = 0.0
        self._silence_fault: bool = False
        self._latched_fault: Optional[str] = None
        self._last_reason: str = "starting"

    def record_audio(self) -> None:
        self._last_audio_time = time.monotonic()
        self._silence_fault = False

    def mark_health_fault(self, reason: str) -> None:
        """Latch a fault. The FIRST reason wins until an explicit clear.

        Why the first one: the supervisor reports "no capture" on every tick
        after a failure, so a last-write-wins latch would overwrite the actual
        root cause ("websocket not connected") with the generic symptom one
        second later. The operator debugging this at 2am needs the cause, not
        the fact that something is still wrong.
        """
        if self._latched_fault is None:
            self._latched_fault = str(reason)
            logger.error("CAPTURE HEALTH FAULT: %s", reason)
        else:
            logger.debug("capture health fault persists: %s (also: %s)",
                         self._latched_fault, reason)

    def adopt_external_health(self, healthy: bool, reason: str) -> None:
        """Latch the audio path's own verdict (src.capture.AssemblyAICapture.health()).

        A healthy verdict never clears a latched fault; only a rebuild does.
        """
        if not healthy:
            self.mark_health_fault(reason)

    def clear_fault(self) -> None:
        """Explicit reset. Called once, when a NEW capture session is built."""
        self._latched_fault = None
        self._silence_fault = False
        self._last_audio_time = 0.0

    def check(self) -> tuple[bool, str]:
        if self._latched_fault is not None:
            return False, f"fault: {self._latched_fault}"
        if self._last_audio_time == 0.0:
            return True, "starting"
        gap = time.monotonic() - self._last_audio_time
        if gap > self.silence_threshold_seconds:
            self._silence_fault = True
            return False, (
                f"silence fault: {gap:.1f}s "
                f"(threshold={self.silence_threshold_seconds}s)"
            )
        return True, f"healthy (last audio {gap:.1f}s ago)"

    @property
    def latched_fault(self) -> Optional[str]:
        return self._latched_fault


class CaptureService:
    """Full-fidelity persistence + health. Not an audio path.

    The shell's `src/capture.py` owns the mic and the WebSocket. This service
    is fed every Turn frame it produces, persists the durable ones, and reports
    its own health back to the shell's status line.
    """

    def __init__(self, config: CaptureConfig):
        self.config = config
        self.transcripts_dir = Path(config.transcripts_dir)
        self.audio_dir = Path(config.audio_dir)
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)
        self.audio_dir.mkdir(parents=True, exist_ok=True)

        self.audio_retention = AudioRetentionManager(
            str(self.audio_dir), config.audio_retention_days
        )
        self.health = CaptureHealth(
            config.silence_threshold_seconds,
            config.heartbeat_interval_seconds,
        )

        self.on_transcript: Optional[Callable[[TranscriptRecord], None]] = None

        self._running = False
        self._thread = None
        self._event_seq = 0
        # Counters — these are what make the durability contract observable.
        self.durable_writes = 0
        self.ephemeral_drops = 0
        self.last_error: Optional[str] = None

    # -- state ---------------------------------------------------------
    def is_running(self) -> bool:
        return self._running

    def is_healthy(self) -> bool:
        ok, _reason = self.health.check()
        return ok

    def health_status(self) -> tuple[bool, str]:
        return self.health.check()

    def start(self) -> None:
        """Mark the engine live and reset per-session fault state."""
        self._running = True
        self.health.clear_fault()
        self.last_error = None
        logger.info("V3 capture engine live (persistence + health)")

    def stop(self) -> None:
        self._running = False
        logger.info("V3 capture engine stopped")

    # -- G6 persistence ------------------------------------------------
    def persist_transcript(self, text: str, is_partial: bool = False,
                           duration: Optional[float] = None) -> TranscriptRecord:
        """Persist (final) or pass through (partial) one STT Turn frame.

        G6: the text handed in is the text written out, byte for byte. No
        normalization, no truncation, no elision. SURGERY C: a partial writes
        nothing to disk.
        """
        raw = text if isinstance(text, str) else str(text)
        is_partial = bool(is_partial)

        record = TranscriptRecord(
            event_id=self._next_event_id(),
            timestamp=datetime.now().isoformat(timespec="milliseconds"),
            raw_text=raw,
            audio_path=None,
            duration_seconds=duration,
            stt_model=self.config.speech_model,
            is_partial=is_partial,
            is_durable=not is_partial,
            chars=len(raw),
        )

        if is_partial:
            # EPHEMERAL. Returned to in-process consumers only. Writing a
            # partial here is what made the salvage corpus unusable.
            self.ephemeral_drops += 1
            logger.debug("ephemeral partial (%d chars) — not persisted",
                         record.chars)
            return record

        path = self.transcripts_dir / f"{record.event_id}.json"
        payload = {
            "event_id": record.event_id,
            "timestamp": record.timestamp,
            "raw_text": record.raw_text,
            "audio_path": record.audio_path,
            "duration_seconds": record.duration_seconds,
            "stt_provider": record.stt_provider,
            "stt_model": record.stt_model,
            "is_partial": record.is_partial,
        }
        # Write to a temp file then replace, so a crash mid-write can never
        # leave a half-written durable transcript that reads as complete.
        tmp = path.with_suffix(".json.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception as e:
            self.last_error = f"durable write failed: {e}"
            logger.error("durable transcript write FAILED (%s): %s",
                         record.event_id, e, exc_info=True)
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            raise

        self.durable_writes += 1
        if record.chars > LENGTH_WARN_CHARS:
            logger.info("persisted long transcript: %s (%d chars)",
                        record.event_id, record.chars)
        else:
            logger.info("persisted transcript: %s (%d chars)",
                        record.event_id, record.chars)
        return record

    def read_transcript(self, event_id: str) -> dict:
        """Read one durable transcript back. Used by verification, not the UI."""
        path = self.transcripts_dir / f"{event_id}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def durable_transcript_ids(self) -> list:
        if not self.transcripts_dir.exists():
            return []
        return sorted(p.stem for p in self.transcripts_dir.glob("*.json"))

    def _next_event_id(self) -> str:
        self._event_seq += 1
        return str(uuid.uuid4())

    # -- durability accounting (observability) --------------------------
    def durability_report(self) -> dict:
        return {
            "durable_writes": self.durable_writes,
            "ephemeral_partials_not_written": self.ephemeral_drops,
            "durable_files_on_disk": len(self.durable_transcript_ids()),
            "last_error": self.last_error,
        }

    # -- consumer hook -------------------------------------------------
    def emit(self, record: TranscriptRecord) -> None:
        if self.on_transcript is None:
            return
        try:
            self.on_transcript(record)
        except Exception as e:
            # A broken consumer must never take dictation down. The record is
            # already durable; the consumer is at fault.
            logger.error("transcript consumer raised (%s): %s",
                         record.event_id, e, exc_info=True)


# ---------------------------------------------------------------------------
# Standalone config loader (engine-only operation, no shell present)
# ---------------------------------------------------------------------------
def load_config(config_path: str = "config.json") -> CaptureConfig:
    config_file = Path(config_path)
    if not config_file.exists():
        config_file = Path(__file__).parent.parent / "config.json"
    if not config_file.exists():
        raise ValueError(
            "config error: config.json not found in current directory or parent"
        )

    with open(config_file, encoding="utf-8") as f:
        data = json.load(f)

    # Key resolution order. NOTE: the key value is never logged, never echoed
    # and never copied anywhere by this module.
    api_key = os.environ.get("ASSEMBLYAI_API_KEY", "")
    if not api_key:
        api_key = (data.get("stt") or {}).get("api_key", "")
    if not api_key:
        api_key = data.get("assemblyai_api_key", "")
    if not api_key:
        raise ValueError("config error: STT API key missing")

    return CaptureConfig(
        api_key=api_key,
        transcripts_dir=(data.get("paths") or {}).get("transcripts", "data/transcripts"),
        audio_dir=(data.get("paths") or {}).get("audio", "data/audio"),
        audio_retention_days=(data.get("audio_retention") or {}).get("retention_days", 7),
        silence_threshold_seconds=(data.get("capture_health") or {}).get(
            "silence_threshold_seconds", 10),
        heartbeat_interval_seconds=(data.get("capture_health") or {}).get(
            "heartbeat_interval_seconds", 30),
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        cfg = load_config()
    except ValueError as e:
        print(f"[CONFIG ERROR] {e}")
        raise SystemExit(1)

    svc = CaptureService(cfg)
    svc.start()
    print(f"V3 capture engine ready — durable transcripts -> {cfg.transcripts_dir}")
    print(f"health: {svc.health_status()}")
    print("This module does not open a microphone. The shell owns the audio path.")
