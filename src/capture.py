#!/usr/bin/env python3
"""
capture.py â€” AssemblyAI Universal-3 streaming capture loop

Real-time streaming STT over the AssemblyAI v3 WebSocket
(`wss://streaming.assemblyai.com/v3/ws`) using the Universal-3.5 Pro model
(`universal-3-5-pro`). Custom vocabulary is preloaded per session via the
`keyterms_prompt` connection parameter so proper names are recognized directly
by the engine â€” there is NO downstream correction/proofreading pass.

Uses sounddevice (no compiler on Windows) + the `websockets` library (already
a dependency). The public surface (CaptureConfig / AssemblyAICapture /
AssemblyAIAuthError) mirrors the previous Deepgram capture so voice_bridge.py
only needs its import line + config keys updated.

Usage:
    from src.capture import AssemblyAICapture, CaptureConfig

    def on_text(text, is_final):
        print(text)

    config = CaptureConfig(api_key="...")
    capture = AssemblyAICapture(config)
    capture.on_transcript = on_text
    capture.start()
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlencode

try:
    import sounddevice as sd
    _HAS_AUDIO = True
except Exception:
    sd = None  # type: ignore
    _HAS_AUDIO = False

try:
    import websockets
    _HAS_WEBSOCKETS = True
except Exception:
    websockets = None  # type: ignore
    _HAS_WEBSOCKETS = False

if _HAS_WEBSOCKETS:
    try:
        _WSConnectionClosed = websockets.exceptions.ConnectionClosed
    except Exception:
        try:
            _WSConnectionClosed = websockets.ConnectionClosed
        except Exception:
            _WSConnectionClosed = Exception  # type: ignore
    try:
        _WSInvalidStatus = websockets.exceptions.InvalidStatus
    except Exception:
        try:
            _WSInvalidStatus = websockets.exceptions.InvalidStatusCode
        except Exception:
            try:
                _WSInvalidStatus = websockets.InvalidStatus
            except Exception:
                _WSInvalidStatus = Exception  # type: ignore
    # websockets renamed the headers kwarg: extra_headers (<14) -> additional_headers (>=14).
    # Detect once so the connect call works regardless of installed version.
    try:
        _ws_ver = tuple(int(p) for p in websockets.__version__.split(".")[:2] if p.isdigit())
    except Exception:
        _ws_ver = (0, 0)
    _WS_HEADERS_KWARG = "additional_headers" if _ws_ver >= (14, 0) else "extra_headers"
else:
    _WSConnectionClosed = Exception  # type: ignore
    _WSInvalidStatus = Exception  # type: ignore
    _WS_HEADERS_KWARG = "additional_headers"


class AssemblyAIAuthError(Exception):
    """Raised when AssemblyAI rejects the API key (401/402/403)."""

    def __init__(self, status: int, message: str = "") -> None:
        self.status = status
        super().__init__(message)


logger = logging.getLogger("capture")


# ---------------------------------------------------------------------------
# AssemblyAI protocol constants
# ---------------------------------------------------------------------------
# Streaming v3 endpoint. Regional variants exist; the global endpoint is fine
# for push-to-talk dictation.
ASSEMBLYAI_URL = "wss://streaming.assemblyai.com/v3/ws"

# The user asked for "Universal-3 Pro". The current Pro streaming model is
# Universal-3.5 Pro (`universal-3-5-pro`); it is the model with documented
# `keyterms_prompt` support, which is what makes the custom-vocabulary preload
# actually work. Override via CaptureConfig.speech_model if you need the
# legacy `universal-3-pro`.
DEFAULT_SPEECH_MODEL = "universal-3-5-pro"

# Names the engine must spell correctly. These are passed as `keyterms_prompt`
# at session open (custom-vocabulary preloading) so recognition improves at the
# engine level â€” no post-hoc correction layer. Max 100 terms, each <=50 chars.
DEFAULT_KEYTERMS: tuple[str, ...] = (
    "Plumb", "Kimi", "GLM", "EC4", "EC8", "Claude", "Renzo", "Santonio",
)


def _status_from_invalid_status(exc: Exception) -> int | None:
    """Extract HTTP status from websockets' invalid-status exception across versions."""
    if hasattr(exc, "response") and exc.response is not None:
        for attr in ("status_code", "status"):
            val = getattr(exc.response, attr, None)
            if isinstance(val, int):
                return val
    import re as _re

    m = _re.search(r"\bHTTP\s+(\d{3})\b", str(exc))
    if m:
        return int(m.group(1))
    return None


# AssemblyAI signals an auth/billing failure mid-session by sending an Error
# frame (close code 1008) *after* the WebSocket has already opened, e.g.
# "Unauthorized Connection: Insufficient funds". Those must be classified as
# auth errors, not transient drops, or the supervisor hot-reconnects forever
# while the UI misleadingly shows "listening".
_AUTH_BILLING_CODES = {401, 402, 403, 1008}
_AUTH_BILLING_KEYWORDS = (
    "insufficient funds",
    "unauthorized",
    "authentication",
    "invalid api key",
    "invalid api_key",
    "billing",
    "quota",
    "credit",
)


def _is_auth_or_billing_error(code, message: str) -> bool:
    """True if an AssemblyAI Error frame indicates an auth/billing problem."""
    try:
        if int(code) in _AUTH_BILLING_CODES:
            return True
    except (TypeError, ValueError):
        pass
    text = (message or "").lower()
    return any(k in text for k in _AUTH_BILLING_KEYWORDS)


def _rms(chunk: bytes) -> float:
    """Root-mean-square level of a 16-bit PCM chunk (~0..32767)."""
    if not chunk or len(chunk) < 2:
        return 0.0
    import array as _array
    try:
        samples = _array.array("h")
        samples.frombytes(chunk)
    except Exception:
        return 0.0
    if not samples:
        return 0.0
    acc = 0.0
    for s in samples:
        acc += float(s) * float(s)
    return (acc / len(samples)) ** 0.5


def _build_ws_url(config: "CaptureConfig") -> str:
    """Build the v3 WebSocket URL with connection params.

    `speech_model`, `sample_rate`, and `keyterms_prompt` are the params that
    matter here. `keyterms_prompt` is a JSON-stringified array of terms the
    engine should bias toward (custom-vocabulary preload). Auth is NOT in the
    URL â€” it goes in the Authorization header (see _run).
    """
    params: dict[str, str] = {
        "speech_model": config.speech_model,
        "sample_rate": str(config.sample_rate),
        # Ensure finalized turns arrive formatted (capitalization/punctuation)
        # so the typed output is clean without a proofreading pass.
        "format_turns": "true",
    }
    if config.keyterms:
        params["keyterms_prompt"] = json.dumps(list(config.keyterms))
    if config.prompt:
        params["prompt"] = config.prompt
    return f"{ASSEMBLYAI_URL}?{urlencode(params)}"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@dataclass
class CaptureConfig:
    api_key: str
    device_index: int | None = None
    # Universal-3.5 Pro is the default; documented to support keyterms_prompt.
    # Set to "universal-3-pro" for the legacy Pro streaming model.
    speech_model: str = DEFAULT_SPEECH_MODEL
    sample_rate: int = 16000
    channels: int = 1
    chunk_size: int = 1600  # ~50 ms of 16-bit mono PCM at 16 kHz (800 samples)
    # Custom vocabulary preload (keyterms_prompt). Defaults to the user's name
    # list. Override/extend via config.json to add domain terms.
    keyterms: tuple[str, ...] = DEFAULT_KEYTERMS
    # Optional natural-language context prompt (AssemblyAI `prompt` param).
    prompt: str = ""
    # Local silence gate (VAD-lite): when the micRMS stays below
    # vad_threshold for vad_silence_seconds, audio stops being sent
    # upstream (the WebSocket stays open; the supervisor resumes feeding
    # on the next utterance). Cuts always-on CPU/network/billing waste.
    # A manual mute (capture.set_muted(True)) always wins over the gate.
    vad_threshold: float = 500.0  # RMS of int16 samples (1600 = a normal voice)
    vad_silence_seconds: float = 3.0
    # Timeouts for the graceful shutdown sequence (ForceEndpoint -> final
    # -> Terminate -> Termination), in seconds.
    final_wait_seconds: float = 1.5
    termination_wait_seconds: float = 1.5


# Health: PortAudio delivers one block every chunk_size/sample_rate (100 ms at
# the 1600/16000 defaults). A continuous gap far larger than that means the
# device stopped delivering audio (powered off / unplugged / driver abort)
# rather than a scheduling hiccup. [PROPOSED] constant, one line to revert;
# does not touch VAD, finalization, provider, model or keyterms.
AUDIO_HEARTBEAT_TIMEOUT = 3.0


def _resolve_input_device(device_index):
    """Re-resolve the configured input device against the live device list.

    A device index captured once at startup goes stale when a mic is
    unplugged, power-cycled, or re-enumerated — Windows can hand the same
    hardware a different PortAudio index. Returns a validated index, or None
    for "system default" (including when the configured index is unusable, so
    the stream opens instead of failing outright).
    """
    if not _HAS_AUDIO:
        return device_index
    try:
        if device_index is None:
            default = sd.default.device
            if default is None:
                default_in = None
            else:
                # sounddevice returns an _InputOutputPair (not a list/tuple);
                # a bare int is also legal. Subscript when possible.
                try:
                    default_in = default[0]
                except Exception:
                    default_in = default
            info = sd.query_devices(default_in, kind="input") if default_in is not None else None
            logger.info(
                "mic device resolved: system default -> index=%r name=%r",
                default_in, (info or {}).get("name"),
            )
            return None
        info = sd.query_devices(device_index, kind="input")
    except Exception as e:
        logger.warning(
            "configured mic device %r unavailable (%s) — falling back to system default",
            device_index, e,
        )
        return None
    if int(info.get("max_input_channels") or 0) < 1:
        logger.warning(
            "mic device %r (%r) has no input channels — falling back to system default",
            device_index, info.get("name"),
        )
        return None
    logger.info(
        "mic device resolved: index=%r name=%r input_channels=%s",
        device_index, info.get("name"), info.get("max_input_channels"),
    )
    return device_index


# ---------------------------------------------------------------------------
# Capture engine
# ---------------------------------------------------------------------------
class AssemblyAICapture:
    """Async streaming capture against the AssemblyAI v3 WebSocket.

    Lifecycle (always-on):
      start()  -> opens WS in a background thread, streams mic audio, emits
                 partials + finals via on_transcript(text, is_final).
      stop()   -> signals shutdown: drains queued audio, sends ForceEndpoint
                 (server finalizes the open turn immediately), waits for the
                 final Turn, sends Terminate, then waits for the Termination
                 message. Closing earlier silently drops the last transcript.
    """

    def __init__(self, config: CaptureConfig):
        self.config = config
        self.on_transcript: Callable[[str, bool], None] | None = None
        self._ws = None
        self._stream = None
        self._audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=200)
        self._running = False
        self._paused = False
        self._finishing = False
        self._thread: threading.Thread | None = None
        self.auth_error: AssemblyAIAuthError | None = None
        # asyncio events (created inside the loop thread)
        self._final_event: asyncio.Event | None = None
        self._terminated_event: asyncio.Event | None = None
        self._done = threading.Event()
        # Connection outcome for start(): set once the WS is connected (no
        # error) or the connect attempt has failed (error stored).
        self._connect_event = threading.Event()
        self._connect_error: Exception | None = None

        # Local silence gate (VAD-lite).
        self._muted = False          # manual mute (UI button) — always wins
        self._gate_running = False   # False while the WS is paused on silence
        self._last_loud = 0.0        # timestamp of the last loud (speech) chunk

        # Runtime liveness signals (Nico 2026-09-25). `_running` is an INTENT
        # flag, not proof the pipeline works: the mic can vanish, the
        # websocket can close, and the send/recv coroutines can all exit while
        # `_running` is still True. These are the smallest dependable signals
        # the existing architecture can expose without touching VAD or
        # finalization.
        self._send_alive = False     # send coroutine inside its loop
        self._recv_alive = False     # recv coroutine inside its loop
        self._ws_alive = False       # websocket connected and not yet closed
        self._last_audio = 0.0       # monotonic ts of the last audio callback
        self._started_at = 0.0       # monotonic ts of start()
        self._last_status = 0        # last PortAudio callback status (dedup)
        self._queue_drops = 0        # audio chunks dropped because queue full

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    def is_running(self) -> bool:
        return self._running

    def health(self) -> tuple[bool, str]:
        """Return ``(healthy, reason)`` for the whole capture pipeline.

        ``is_running()`` only proves the INTENT to run. This checks the four
        things that can silently die while `_running` stays True: the audio
        device, the websocket, and the send/recv coroutines. Called by the
        supervisor each tick; read-only and side-effect free.
        """
        if self._finishing:
            # Deliberate teardown in progress (ForceEndpoint/Terminate) — the
            # stream is already closed by stop(). Not a fault.
            return True, "finishing"
        if not self._running:
            return False, "not running"
        if self._thread is None or not self._thread.is_alive():
            return False, "capture thread dead"
        now = time.monotonic()
        if self._started_at and now - self._started_at <= AUDIO_HEARTBEAT_TIMEOUT:
            # Grace window right after start(): the websocket and stream may
            # still be opening. start() already blocks on connect itself.
            return True, "starting"
        if not self._ws_alive:
            return False, "websocket not connected"
        if not self._recv_alive:
            return False, "recv loop dead"
        if not self._send_alive:
            return False, "send loop dead"
        stream = self._stream
        if stream is None:
            return False, "audio stream not open"
        try:
            if not stream.active:
                return False, "audio stream inactive"
        except Exception as e:
            return False, f"audio stream unreadable: {e}"
        if self._last_audio <= 0.0:
            return False, "audio callback never delivered a block"
        gap = now - self._last_audio
        if gap > AUDIO_HEARTBEAT_TIMEOUT:
            return False, f"no audio for {gap:.1f}s (device lost?)"
        return True, "healthy"

    def is_healthy(self) -> bool:
        ok, _reason = self.health()
        return ok

    def pause(self) -> None:
        self._paused = True
        logger.info("Capture paused")

    def resume(self) -> None:
        self._paused = False
        logger.info("Capture resumed")

    # ------------------------------------------------------------------
    # Silence gate (VAD-lite) + manual mute
    # ------------------------------------------------------------------
    def set_muted(self, muted: bool) -> None:
        """Manual mute/unmute (UI button). Wins over the silence gate."""
        self._muted = bool(muted)
        self._gate_running = not self._muted
        logger.info("Capture muted=%s", self._muted)
        if self._muted:
            self._drain_audio()

    def is_muted(self) -> bool:
        return self._muted

    def is_gate_running(self) -> bool:
        """True when audio is actually being fed upstream right now."""
        return self._gate_running

    def _drain_audio(self) -> None:
        try:
            while True:
                self._audio_queue.get_nowait()
        except queue.Empty:
            pass

    def _gate_should_send(self, rms: float) -> bool:
        """Decide whether this audio chunk should be fed upstream.

        False when manually muted. Otherwise True while loud audio has been
        heard within the last ``vad_silence_seconds`` (silence gate).
        """
        if self._muted:
            self._gate_running = False
            return False
        if rms >= self.config.vad_threshold:
            self._last_loud = time.monotonic()
            self._gate_running = True
            return True
        live = not self.config.vad_silence_seconds or (
            time.monotonic() - self._last_loud < self.config.vad_silence_seconds
        )
        self._gate_running = live
        return live

    def stop(self) -> None:
        """Initiate graceful shutdown and wait for the session to terminate.

        Sets the finishing flag so the run loop performs the
        ForceEndpoint -> Terminate sequence and drains the final transcript.
        Blocks (bounded by the configured timeouts) until the WS thread exits,
        which guarantees the billed session is actually closed.
        """
        if not self._running and not (self._thread and self._thread.is_alive()):
            return
        self._finishing = True
        # Stop capturing NEW mic audio; queued audio still flushes to the server.
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        # Wait for the background thread to finish the terminate sequence.
        if self._thread and self._thread.is_alive():
            self._done.wait(timeout=(
                self.config.final_wait_seconds
                + self.config.termination_wait_seconds
                + 2.0
            ))
            try:
                self._thread.join(timeout=1.0)
            except Exception:
                pass
        self._thread = None
        if self._queue_drops:
            logger.info("Capture stopped | dropped audio blocks=%d", self._queue_drops)
        else:
            logger.info("Capture stopped")

    # ------------------------------------------------------------------
    # WebSocket receiver
    # ------------------------------------------------------------------
    async def _recv_loop(self) -> None:
        if not _HAS_WEBSOCKETS or not self._ws:
            return
        self._recv_alive = True
        try:
            async for msg in self._ws:
                if not self._running:
                    break
                try:
                    data = json.loads(msg)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict):
                    continue
                mtype = data.get("type")

                if mtype == "Turn":
                    transcript = (data.get("transcript") or "").strip()
                    end_of_turn = bool(data.get("end_of_turn"))
                    formatted = data.get("turn_is_formatted", True)
                    if not transcript:
                        continue
                    # For Universal-3.5 Pro a finalized turn has both flags true
                    # and arrives once (no double-final like Universal Streaming).
                    is_final = end_of_turn and formatted
                    if self.on_transcript:
                        self.on_transcript(transcript, is_final)
                    if is_final and self._final_event is not None:
                        self._final_event.set()
                elif mtype == "Error":
                    code = data.get("error_code")
                    message = data.get("error", "") or ""
                    logger.error(f"AssemblyAI error {code}: {message}")
                    if _is_auth_or_billing_error(code, message):
                        try:
                            status = int(code)
                        except (TypeError, ValueError):
                            status = 1008
                        self.auth_error = AssemblyAIAuthError(
                            status,
                            f"AssemblyAI {code}: {message} — check "
                            "ASSEMBLYAI_API_KEY and your AssemblyAI "
                            "billing/credits.",
                        )
                        self._connect_error = self.auth_error
                    self._running = False
                    break
                elif mtype == "Termination":
                    logger.info(
                        "AssemblyAI session terminated: "
                        f"{data.get('audio_duration_seconds')}s audio, "
                        f"{data.get('session_duration_seconds')}s session"
                    )
                    if self._terminated_event is not None:
                        self._terminated_event.set()
                    self._running = False
                    break
                # Begin / SpeechStarted / Heartbeat / SpeakerRevision: ignored.
        except _WSConnectionClosed as e:
            # Health propagation (Nico 2026-09-25): the server closed without
            # a Termination handshake. Previously this was logged at INFO and
            # _running stayed True, so the supervisor never noticed and the
            # bridge sat "listening" while nothing was transcribed again.
            self._ws_alive = False
            if self._finishing:
                logger.info("AssemblyAI WS closed (finishing): %s", e)
            else:
                logger.warning(
                    "AssemblyAI WS closed unexpectedly: %s — marking capture unhealthy",
                    e,
                )
                self._running = False
        except Exception as e:
            logger.error(f"Recv error: {e}", exc_info=True)
            self._ws_alive = False
            if not self._finishing:
                self._running = False
        finally:
            self._recv_alive = False
            if self._terminated_event is not None:
                self._terminated_event.set()

    # ------------------------------------------------------------------
    # Audio sender
    # ------------------------------------------------------------------
    async def _send_loop(self) -> None:
        if not _HAS_WEBSOCKETS or not _HAS_AUDIO or not self._ws:
            return
        self._send_alive = True
        try:
            while self._running:
                if self._paused:
                    # Drain mic audio captured while paused (e.g. during TTS)
                    # so we don't transcribe our own voice when we resume.
                    try:
                        while True:
                            self._audio_queue.get_nowait()
                    except queue.Empty:
                        pass
                    await asyncio.sleep(0.05)
                    continue
                try:
                    chunk = self._audio_queue.get(timeout=0.05)
                except queue.Empty:
                    # Once finishing, stop feeding audio so the finish loop
                    # can force-endpoint the turn promptly.
                    if self._finishing:
                        return
                    continue

                try:
                    # Raw 16-bit PCM as a binary frame — no JSON/base64 wrapper.
                    await self._ws.send(chunk)
                except _WSConnectionClosed as e:
                    self._ws_alive = False
                    if self._finishing:
                        logger.info("Send loop: WS closed (finishing): %s", e)
                    else:
                        logger.warning(
                            "Send loop: WS closed unexpectedly: %s — marking capture unhealthy",
                            e,
                        )
                        self._running = False
                    return
                await asyncio.sleep(0.001)
        except Exception as e:
            logger.error(f"Send error: {e}", exc_info=True)
            if not self._finishing:
                self._ws_alive = False
                self._running = False
        finally:
            self._send_alive = False

    # ------------------------------------------------------------------
    # Push-to-talk shutdown: ForceEndpoint -> final -> Terminate -> Termination
    # ------------------------------------------------------------------
    async def _safe_send(self, payload: dict) -> None:
        if not self._ws:
            return
        try:
            await self._ws.send(json.dumps(payload))
        except _WSConnectionClosed:
            pass
        except Exception as e:
            logger.error(f"Send error on {payload.get('type')}: {e}")

    async def _finish_loop(self) -> None:
        # Wait until stop() flips the finishing flag from another thread.
        while self._running and not self._finishing:
            await asyncio.sleep(0.05)
        if not self._ws:
            return

        # Give the send loop a beat to flush any buffered audio first.
        await asyncio.sleep(0.1)

        # 1) Tell the server to finalize the current turn right now.
        if self._final_event is not None:
            self._final_event.clear()
        await self._safe_send({"type": "ForceEndpoint"})

        # 2) Wait for that final Turn (recv_loop sets _final_event).
        if self._final_event is not None:
            try:
                await asyncio.wait_for(
                    self._final_event.wait(),
                    timeout=self.config.final_wait_seconds,
                )
            except asyncio.TimeoutError:
                logger.warning("No final Turn after ForceEndpoint (timeout)")

        # 3) Terminate the session. Terminate is required â€” un-terminated
        #    sessions keep billing until the 3-hour server auto-close.
        await self._safe_send({"type": "Terminate"})

        # 4) Keep reading until the Termination message arrives.
        if self._terminated_event is not None:
            try:
                await asyncio.wait_for(
                    self._terminated_event.wait(),
                    timeout=self.config.termination_wait_seconds,
                )
            except asyncio.TimeoutError:
                logger.warning("No Termination message (timeout)")

        self._running = False

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    async def _run(self) -> None:
        self._done.clear()
        if not _HAS_WEBSOCKETS or not _HAS_AUDIO:
            logger.error("Missing sounddevice or websockets. Cannot start capture.")
            self._running = False
            self._connect_error = ConnectionError(
                "Missing sounddevice or websockets; cannot start capture."
            )
            self._connect_event.set()
            return

        url = _build_ws_url(self.config)

        try:
            # AUTH: Authorization header = the raw API key (NO "Bearer"/"Token"
            # prefix). A token in the URL leaks into server/proxy logs.
            headers = {"Authorization": self.config.api_key}
            self._ws = await websockets.connect(url, **{_WS_HEADERS_KWARG: headers})
        except _WSInvalidStatus as e:
            status = _status_from_invalid_status(e)
            if status in (401, 402, 403):
                logger.error(f"WS connect rejected: HTTP {status} (auth/billing)")
                self._running = False
                self.auth_error = AssemblyAIAuthError(
                    status,
                    f"AssemblyAI rejected the API key: HTTP {status}. "
                    "Check ASSEMBLYAI_API_KEY and your AssemblyAI billing/credits.",
                )
                self._connect_error = self.auth_error
                self._connect_event.set()
                return
            logger.error(f"WS connect failed: HTTP {status}")
            self._running = False
            self._connect_error = ConnectionError(
                f"AssemblyAI WS connect failed: HTTP {status}"
            )
            self._connect_event.set()
            return
        except Exception as e:
            logger.error(f"WS connect failed: {e}")
            self._running = False
            self._connect_error = ConnectionError(
                f"AssemblyAI WS connect failed: {e}"
            )
            self._connect_event.set()
            return

        # Connection established — unblock start() so the caller knows the
        # session is live before audio starts flowing.
        self._ws_alive = True
        logger.info("AssemblyAI websocket connected")
        self._connect_event.set()

        # Audio callback -> queue
        def _audio_callback(indata, frames, time_info, status):
            # Heartbeat FIRST (before the paused/not-running early return):
            # this proves the DEVICE is still delivering blocks, which is the
            # signal used to detect a powered-off / unplugged mic. One line of
            # arithmetic per block — no logging here.
            self._last_audio = time.monotonic()
            stat = int(status) if status else 0
            if stat != self._last_status:
                if stat:
                    logger.warning(
                        "audio callback status=0x%X (PortAudio overflow/underflow or device fault)",
                        stat,
                    )
                else:
                    logger.info("audio callback status cleared")
                self._last_status = stat
            if self._paused or not self._running:
                return
            # RawInputStream hands a cffi buffer (not a numpy array) -> bytes()
            chunk = bytes(indata)
            # Silence gate: skip upstream feeding while quiet/manually muted,
            # draining the queue so stale audio is dropped, not delayed.
            if not self._gate_should_send(_rms(chunk)):
                self._drain_audio()
                return
            try:
                self._audio_queue.put_nowait(chunk)
            except queue.Full:
                # Counted, not logged per chunk: 200 blocks = ~20 s of audio
                # buffer, so this is rare, and per-chunk logging would swamp
                # the log at 16 kHz.
                self._queue_drops += 1
                if self._queue_drops == 1 or self._queue_drops % 1000 == 0:
                    logger.warning(
                        "audio queue full — dropping chunk (#%d total)",
                        self._queue_drops,
                    )

        try:
            device = _resolve_input_device(self.config.device_index)
            self._stream = sd.RawInputStream(
                samplerate=self.config.sample_rate,
                channels=self.config.channels,
                dtype="int16",
                blocksize=self.config.chunk_size,
                device=device,
                callback=_audio_callback,
            )
            self._stream.start()
        except Exception as e:
            logger.error(f"Mic init failed: {e}", exc_info=True)
            self._running = False
            await self._safe_send({"type": "Terminate"})
            return

        logger.info(
            f"Capture started (model={self.config.speech_model}, "
            f"{len(self.config.keyterms)} keyterms)"
        )

        try:
            await asyncio.gather(
                self._recv_loop(),
                self._send_loop(),
                self._finish_loop(),
                return_exceptions=True,
            )
        except Exception as e:
            logger.error(f"Run loop error: {e}")
        finally:
            self._running = False
            self._ws_alive = False
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            if self._ws:
                try:
                    await self._ws.close()
                except Exception:
                    pass
                self._ws = None
            self._done.set()

    def start(self, connect_timeout: float = 10.0) -> None:
        """Start capture (runs asyncio event loop in a thread).

        Blocks (bounded by ``connect_timeout``) until the WebSocket is either
        connected or the connect attempt has failed, then raises
        :class:`AssemblyAIAuthError` on 401/402/403 or :class:`ConnectionError`
        for any other connect failure â€” so callers (the supervisor) can react
        to a bad key instead of spinning reconnects.
        """
        if self._thread and self._thread.is_alive():
            self.stop()
        self._running = True
        self._paused = False
        self._finishing = False
        self._audio_queue = queue.Queue(maxsize=200)
        self.auth_error = None
        self._done.clear()
        self._connect_error = None
        self._connect_event.clear()
        # Health signal reset for the new session.
        self._ws_alive = False
        self._recv_alive = False
        self._send_alive = False
        self._last_audio = 0.0
        self._last_status = 0
        self._queue_drops = 0
        self._started_at = time.monotonic()

        def _target():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._final_event = asyncio.Event()
            self._terminated_event = asyncio.Event()
            try:
                loop.run_until_complete(self._run())
            except Exception as e:
                # Never let an unhandled error leave start() hanging.
                if self._connect_error is None:
                    self._connect_error = e
                self._connect_event.set()
            finally:
                loop.close()

        self._thread = threading.Thread(target=_target, daemon=True)
        self._thread.start()

        if not self._connect_event.wait(timeout=connect_timeout):
            self._running = False
            raise ConnectionError(
                f"AssemblyAI WS connect timed out after {connect_timeout}s"
            )
        if self._connect_error is not None:
            raise self._connect_error

    # ------------------------------------------------------------------
    # Synchronous helpers
    # ------------------------------------------------------------------
    def is_auth_error(self) -> bool:
        return self.auth_error is not None
