"""Runtime reliability tests (Nico 2026-09-25, Don ordered fix).

Covers:
  - capture pipeline health detection (audio heartbeat, ws, send/recv, stream)
  - supervisor gate: rebuild on UNHEALTHY-but-running, keep when healthy
  - dispatcher thread liveness
  - timestamped/leveled/named log sink (setup_logging)
No mic, no network, no tkinter mainloop.
"""

import logging
import re
import threading
import time
from unittest.mock import patch

import src.voice_bridge as vb
from src.capture import (
    AUDIO_HEARTBEAT_TIMEOUT,
    AssemblyAICapture,
    CaptureConfig,
)
from src.voice_bridge import WakeWordBridge


def _make_bridge() -> WakeWordBridge:
    with patch.object(vb, "load_config") as mock_cfg, \
         patch.object(vb, "AssemblyAICapture"):
        mock_cfg.return_value = {
            "mode": "wake_word",
            "wake_words": ["keel"],
            "armed_timeout_seconds": 12.0,
            "mic_device": "default",
            "assemblyai_api_key": "test-key",
            "speech_model": "universal-3-5-pro",
            "keyterms": [],
            "sample_rate": 16000,
            "channels": 1,
            "supervisor_interval_seconds": 2.0,
        }
        return WakeWordBridge()


class _FakeCapture:
    def __init__(self, healthy=True, running=True, auth_error=None):
        self._healthy = healthy
        self._running = running
        self.auth_error = auth_error
        self.stop_calls = 0
        self.started = False

    def is_running(self):
        return self._running

    def health(self):
        if self._healthy:
            return True, "healthy"
        return False, "no audio for 3.1s (device lost?)"

    def is_healthy(self):
        return self._healthy

    def start(self, connect_timeout=10.0):
        self.started = True

    def stop(self):
        self.stop_calls += 1

    def is_auth_error(self):
        return self.auth_error is not None


class _DeadThread:
    def is_alive(self):
        return False


# ---------------------------------------------------------------------------
# Capture health detection
# ---------------------------------------------------------------------------
def _started_capture(**overrides) -> AssemblyAICapture:
    cap = AssemblyAICapture(CaptureConfig(api_key="test-key"))
    cap._running = True
    cap._thread = threading.current_thread()
    cap._started_at = time.monotonic() - 100.0  # outside the start grace window
    cap._ws_alive = True
    cap._recv_alive = True
    cap._send_alive = True
    cap._stream = None
    cap._last_audio = 0.0
    for key, value in overrides.items():
        setattr(cap, key, value)
    return cap


def test_heartbeat_timeout_outlives_a_single_audio_block():
    # chunk_size/sample_rate = 1600/16000 = 100 ms; the timeout must be many
    # blocks long so ordinary scheduling jitter never trips a reconnect.
    assert AUDIO_HEARTBEAT_TIMEOUT >= 1.0


def test_health_false_when_not_running():
    cap = AssemblyAICapture(CaptureConfig(api_key="test-key"))
    ok, reason = cap.health()
    assert ok is False and reason == "not running"
    assert cap.is_healthy() is False


def test_health_true_while_finishing_teardown():
    cap = _started_capture(_finishing=True, _running=False, _thread=None)
    ok, reason = cap.health()
    assert ok is True and reason == "finishing"


def test_health_reports_starting_within_grace_window():
    cap = _started_capture(_started_at=time.monotonic(), _ws_alive=False)
    ok, reason = cap.health()
    assert ok is True and reason == "starting"


def test_health_detects_websocket_loss():
    cap = _started_capture(_ws_alive=False)
    assert cap.health() == (False, "websocket not connected")


def test_health_detects_dead_recv_loop():
    cap = _started_capture(_recv_alive=False)
    assert cap.health() == (False, "recv loop dead")


def test_health_detects_dead_send_loop():
    cap = _started_capture(_send_alive=False)
    assert cap.health() == (False, "send loop dead")


def test_health_detects_dead_capture_thread():
    cap = _started_capture(_thread=_DeadThread())
    assert cap.health() == (False, "capture thread dead")


def test_health_detects_missing_audio_stream():
    cap = _started_capture(_stream=None)
    assert cap.health() == (False, "audio stream not open")


def test_health_detects_inactive_audio_stream():
    class _Stream:
        active = False

    cap = _started_capture(_stream=_Stream())
    assert cap.health() == (False, "audio stream inactive")


def test_health_detects_never_delivered_audio():
    class _Stream:
        active = True

    cap = _started_capture(_stream=_Stream(), _last_audio=0.0)
    assert cap.health() == (False, "audio callback never delivered a block")


def test_health_detects_audio_heartbeat_gap_device_lost():
    class _Stream:
        active = True

    cap = _started_capture(
        _stream=_Stream(),
        _last_audio=time.monotonic() - (AUDIO_HEARTBEAT_TIMEOUT + 2.0),
    )
    ok, reason = cap.health()
    assert ok is False
    assert reason.startswith("no audio for")


def test_health_true_when_everything_is_alive():
    class _Stream:
        active = True

    cap = _started_capture(_stream=_Stream(), _last_audio=time.monotonic())
    assert cap.health() == (True, "healthy")
    assert cap.is_healthy() is True


def test_running_flag_alone_is_not_reported_as_healthy():
    # Regression guard: `_running=True` must not be sufficient by itself.
    cap = _started_capture()
    assert cap.is_running() is True
    ok, _ = cap.health()
    assert ok is False  # stream is None in this state


# ---------------------------------------------------------------------------
# Supervisor gate
# ---------------------------------------------------------------------------
def test_supervisor_rebuilds_unhealthy_but_running_capture():
    bridge = _make_bridge()
    old = _FakeCapture(healthy=False, running=True)
    bridge.capture = old
    new = _FakeCapture(healthy=True, running=True)

    def _sleep(seconds):
        bridge._stopping = True

    with patch.object(bridge, "_build_capture", return_value=new), \
         patch.object(WakeWordBridge, "_sync_mute_button"), \
         patch.object(WakeWordBridge, "_set_status"), \
         patch("src.voice_bridge.time.sleep", side_effect=_sleep):
        bridge._supervisor()

    assert old.stop_calls == 1
    assert bridge.capture is new
    assert new.started is True
    bridge._stopping = True


def test_supervisor_keeps_healthy_capture():
    bridge = _make_bridge()
    old = _FakeCapture(healthy=True, running=True)
    bridge.capture = old

    def _sleep(seconds):
        bridge._stopping = True

    with patch.object(bridge, "_build_capture") as build, \
         patch.object(WakeWordBridge, "_sync_mute_button"), \
         patch.object(WakeWordBridge, "_set_status"), \
         patch("src.voice_bridge.time.sleep", side_effect=_sleep):
        bridge._supervisor()

    build.assert_not_called()
    assert old.stop_calls == 0
    assert bridge.capture is old
    bridge._stopping = True


def test_supervisor_rebuilds_stopped_capture():
    bridge = _make_bridge()
    old = _FakeCapture(healthy=True, running=False)
    bridge.capture = old
    new = _FakeCapture(healthy=True, running=True)

    def _sleep(seconds):
        bridge._stopping = True

    with patch.object(bridge, "_build_capture", return_value=new), \
         patch.object(WakeWordBridge, "_sync_mute_button"), \
         patch.object(WakeWordBridge, "_set_status"), \
         patch("src.voice_bridge.time.sleep", side_effect=_sleep):
        bridge._supervisor()

    assert old.stop_calls == 1
    assert bridge.capture is new
    bridge._stopping = True


def test_supervisor_builds_capture_when_none():
    bridge = _make_bridge()
    bridge.capture = None
    new = _FakeCapture(healthy=True, running=True)

    def _sleep(seconds):
        bridge._stopping = True

    with patch.object(bridge, "_build_capture", return_value=new), \
         patch.object(WakeWordBridge, "_sync_mute_button"), \
         patch.object(WakeWordBridge, "_set_status"), \
         patch("src.voice_bridge.time.sleep", side_effect=_sleep):
        bridge._supervisor()

    assert bridge.capture is new
    assert new.started is True
    bridge._stopping = True


# ---------------------------------------------------------------------------
# Dispatcher liveness
# ---------------------------------------------------------------------------
def test_ensure_dispatcher_keeps_live_thread():
    bridge = _make_bridge()
    before = bridge._dispatch_thread
    assert before is not None and before.is_alive()
    bridge._ensure_dispatcher()
    assert bridge._dispatch_thread is before
    bridge._stopping = True


def test_ensure_dispatcher_restarts_dead_thread():
    bridge = _make_bridge()
    bridge._dispatch_thread = _DeadThread()
    bridge._ensure_dispatcher()
    replacement = bridge._dispatch_thread
    assert replacement is not None and replacement.is_alive()
    bridge._stopping = True


def test_ensure_dispatcher_does_nothing_while_stopping():
    bridge = _make_bridge()
    alive = bridge._dispatch_thread
    bridge._stopping = True
    bridge._dispatch_thread = _DeadThread()
    bridge._ensure_dispatcher()
    assert isinstance(bridge._dispatch_thread, _DeadThread), \
        "no replacement thread must be created while shutting down"
    bridge._stopping = False
    bridge._dispatch_thread = alive
    bridge._stopping = True


# ---------------------------------------------------------------------------
# Logging / observability
# ---------------------------------------------------------------------------
def test_setup_logging_is_timestamped_named_and_idempotent(tmp_path, monkeypatch):
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    logfile = tmp_path / "bridge.log"
    try:
        root.handlers = []
        root.setLevel(logging.WARNING)
        monkeypatch.setattr(vb, "_log_file_path", lambda: logfile)

        vb.setup_logging()
        ours = [h for h in root.handlers if getattr(h, "_voicebridge", False)]
        assert ours, "setup_logging installed no handlers"
        assert root.level == logging.INFO
        for handler in ours:
            assert handler.level == logging.INFO
            assert handler.formatter is not None
            assert "%(asctime)s" in handler.formatter._fmt
            assert "levelname" in handler.formatter._fmt
            assert "name)s" in handler.formatter._fmt

        count = len(root.handlers)
        vb.setup_logging()
        assert len(root.handlers) == count, "setup_logging must be idempotent"

        logging.getLogger("capture").info("AssemblyAI websocket connected")
        for handler in ours:
            handler.flush()
        text = logfile.read_text(encoding="utf-8")
        assert "AssemblyAI websocket connected" in text
        assert "capture" in text
        assert "INFO" in text
        assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", text)
    finally:
        for handler in list(root.handlers):
            if getattr(handler, "_voicebridge", False):
                try:
                    handler.close()
                except Exception:
                    pass
                root.removeHandler(handler)
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


def test_setup_logging_does_not_double_write_when_stderr_is_the_log(tmp_path, monkeypatch):
    """pythonw path: _setup_stdio() already points stderr at bridge.log, so
    setup_logging must not add a second FileHandler for the same file."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    logfile = tmp_path / "bridge.log"
    logfile.parent.mkdir(parents=True, exist_ok=True)

    class _FakeStderr:
        name = str(logfile)

    try:
        root.handlers = []
        root.setLevel(logging.WARNING)
        monkeypatch.setattr(vb, "_log_file_path", lambda: logfile)
        monkeypatch.setattr(vb.sys, "stderr", _FakeStderr())
        vb.setup_logging()
        file_handlers = [
            h for h in root.handlers
            if getattr(h, "_voicebridge", False) and isinstance(h, logging.FileHandler)
        ]
        assert file_handlers == [], "duplicate FileHandler for the same log path"
    finally:
        for handler in list(root.handlers):
            if getattr(handler, "_voicebridge", False):
                try:
                    handler.close()
                except Exception:
                    pass
                root.removeHandler(handler)
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
