"""Silence gate (VAD-lite) + manual mute tests for capture.py.

No mic, no network: drives _gate_should_send / set_muted / is_muted with
synthetic RMS values and a mocked monotonic clock.
"""

import struct
from unittest.mock import patch

from src.capture import AssemblyAICapture, CaptureConfig, _rms


def _make_capture(**vad_kwargs) -> AssemblyAICapture:
    cfg = CaptureConfig(api_key="test-key", **vad_kwargs)
    return AssemblyAICapture(cfg)


def _loud_chunk(rms: float) -> bytes:
    """Build a 16-bit PCM chunk whose RMS is ~= rms (constant amplitude)."""
    n = 800  # one 50 ms frame at 16 kHz
    return struct.pack(f"<{n}h", *([int(rms)] * n))


def test_rms_helper():
    silence = bytes(1600)
    assert _rms(silence) == 0.0
    x = _loud_chunk(1000.0)
    assert 900.0 < _rms(x) < 1100.0


def test_gate_holds_while_speech_then_closes_after_silence():
    cap = _make_capture(vad_threshold=500.0, vad_silence_seconds=3.0)
    fake = iter([100.0, 101.0, 102.0, 103.5])
    with patch("src.capture.time.monotonic", side_effect=fake):
        # Fresh gate: first chunk is loud -> send, sets _last_loud.
        assert cap._gate_should_send(5000.0) is True
        # Within the 3s silence window -> still sending.
        assert cap._gate_should_send(100.0) is True
        assert cap._gate_should_send(100.0) is True
        # Past 3s of quiet -> gate closes.
        assert cap._gate_should_send(100.0) is False


def test_gate_closes_after_window_elapses_when_quiet():
    cap = _make_capture(vad_threshold=500.0, vad_silence_seconds=3.0)
    with patch("src.capture.time.monotonic", side_effect=[1.0, 100.0]):
        assert cap._gate_should_send(5000.0) is True
        # Long silence but the configured window still gates it out.
        assert cap._gate_should_send(10.0) is False


def test_manual_mute_wins_over_gate():
    cap = _make_capture(vad_threshold=500.0, vad_silence_seconds=3.0)
    cap.set_muted(True)
    assert cap.is_muted() is True
    assert cap.is_gate_running() is False
    assert cap._gate_should_send(5000.0) is False  # loud but muted
    cap.set_muted(False)
    assert cap.is_muted() is False
    with patch("src.capture.time.monotonic", return_value=42.0):
        assert cap._gate_should_send(5000.0) is True
        assert cap.is_gate_running() is True


def test_muted_drains_queued_audio():
    cap = _make_capture()
    cap._audio_queue.put(b"queued")
    cap._audio_queue.put(b"stale")
    cap.set_muted(True)
    assert cap._audio_queue.empty()


def test_low_threshold_keeps_gate_open_on_quiet_room():
    cap = _make_capture(vad_threshold=50.0, vad_silence_seconds=1.0)
    with patch("src.capture.time.monotonic", side_effect=[1.0, 1.2, 1.4, 2.5]):
        assert cap._gate_should_send(200.0) is True
        assert cap._gate_should_send(60.0) is True  # still above threshold
        assert cap._gate_should_send(60.0) is True
        # Quiet drops below threshold -> closes after the window elapses.
        assert cap._gate_should_send(10.0) is False