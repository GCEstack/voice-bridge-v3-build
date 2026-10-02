"""Wake-word state-machine tests for WakeWordBridge (no mic, no network)."""

from unittest.mock import MagicMock, patch

import src.voice_bridge as vb
from src.voice_bridge import WakeWordBridge


def _make_bridge() -> WakeWordBridge:
    with patch.object(vb, "load_config") as mock_cfg, \
         patch.object(vb, "AssemblyAICapture"):
        mock_cfg.return_value = {
            "mode": "wake_word",
            "wake_words": ["hey keel", "ok keel", "okay keel", "keel"],
            "armed_timeout_seconds": 12.0,
            "mic_device": "default",
            "assemblyai_api_key": "test-key",
            "speech_model": "universal-3-5-pro",
            "keyterms": ["Kimi", "GLM"],
            "sample_rate": 16000,
            "channels": 1,
            "supervisor_interval_seconds": 2.0,
        }
        return WakeWordBridge()


@patch.object(vb, "type_text")
@patch.object(vb, "press_enter")
@patch.object(vb, "execute_command")
def test_ambient_speech_ignored_while_sleeping(mock_exec, mock_enter, mock_type):
    bridge = _make_bridge()
    bridge._set_state(WakeWordBridge.SLEEPING)
    bridge._handle_final("the quick brown fox jumps over the lazy dog")
    mock_type.assert_not_called()
    mock_enter.assert_not_called()
    assert bridge.state == WakeWordBridge.SLEEPING


@patch.object(vb, "type_text")
@patch.object(vb, "press_enter")
@patch.object(vb, "execute_command")
def test_wake_word_plus_payload_is_typed_with_word_stripped(mock_exec, mock_enter, mock_type):
    bridge = _make_bridge()
    bridge._set_state(WakeWordBridge.SLEEPING)
    bridge._handle_final("keel open the notion board")
    assert bridge.state == WakeWordBridge.ARMED
    mock_type.assert_called_once_with("open the notion board ", interval=0.01)
    mock_enter.assert_not_called()


@patch.object(vb, "type_text")
@patch.object(vb, "press_enter")
@patch.object(vb, "execute_command")
def test_bare_wake_word_arms_but_types_nothing(mock_exec, mock_enter, mock_type):
    bridge = _make_bridge()
    bridge._set_state(WakeWordBridge.SLEEPING)
    bridge._handle_final("hey keel")
    assert bridge.state == WakeWordBridge.ARMED
    mock_type.assert_not_called()


@patch.object(vb, "type_text")
@patch.object(vb, "press_enter")
@patch.object(vb, "execute_command")
def test_armed_utterance_typed_without_wake_word(mock_exec, mock_enter, mock_type):
    bridge = _make_bridge()
    bridge._set_state(WakeWordBridge.ARMED)
    bridge._refresh_arm()
    bridge._handle_final("run process seventy nine")
    mock_type.assert_called_once_with("run process seventy nine ", interval=0.01)
    mock_enter.assert_not_called()


@patch.object(vb, "type_text")
@patch.object(vb, "press_enter")
@patch.object(vb, "execute_command")
def test_sleep_command_disarms(mock_exec, mock_enter, mock_type):
    bridge = _make_bridge()
    bridge._set_state(WakeWordBridge.ARMED)
    bridge._refresh_arm()
    bridge._handle_final("sleep")
    assert bridge.state == WakeWordBridge.SLEEPING
    mock_type.assert_not_called()


@patch.object(vb, "type_text")
@patch.object(vb, "press_enter")
@patch.object(vb, "execute_command")
def test_wake_word_then_sleep_command_disarms(mock_exec, mock_enter, mock_type):
    bridge = _make_bridge()
    bridge._set_state(WakeWordBridge.ARMED)
    bridge._refresh_arm()
    bridge._handle_final("keel sleep")
    assert bridge.state == WakeWordBridge.SLEEPING


@patch.object(vb, "type_text")
@patch.object(vb, "press_enter")
@patch.object(vb, "execute_command")
def test_substring_guard_apex_not_triggered(mock_exec, mock_enter, mock_type):
    bridge = _make_bridge()
    bridge._set_state(WakeWordBridge.SLEEPING)
    bridge._handle_final("apex predator results are in")
    assert bridge.state == WakeWordBridge.SLEEPING
    mock_type.assert_not_called()


@patch.object(vb, "type_text")
@patch.object(vb, "press_enter")
@patch.object(vb, "execute_command")
def test_armed_command_executes_instead_of_typing(mock_exec, mock_enter, mock_type):
    bridge = _make_bridge()
    bridge._set_state(WakeWordBridge.ARMED)
    bridge._refresh_arm()
    bridge._handle_final("copy that")
    mock_exec.assert_called_once_with("copy")
    mock_type.assert_not_called()


@patch.object(vb, "type_text")
@patch.object(vb, "press_enter")
@patch.object(vb, "execute_command")
def test_wake_word_variants_all_match(mock_exec, mock_enter, mock_type):
    for variant in ("hey keel", "ok keel", "okay keel", "Keel"):
        bridge = _make_bridge()
        bridge._set_state(WakeWordBridge.SLEEPING)
        bridge._handle_final(f"{variant} do the thing")
        assert bridge.state == WakeWordBridge.ARMED, f"{variant} did not arm"
        mock_type.assert_called_with("do the thing ", interval=0.01)
        mock_type.reset_mock()


@patch.object(vb, "type_text")
@patch.object(vb, "press_enter")
@patch.object(vb, "execute_command")
def test_ambient_session_commands_ignored_while_sleeping(mock_exec, mock_enter, mock_type):
    """Ambient 'exit'/'continue'/etc. must not arm, sleep, or kill the bridge.
    The pause/resume phrases are also inert while SLEEPING (they only act
    while the bridge is woken / in continuous mode)."""
    for phrase in ("exit", "quit", "continue", "go ahead", "sleep",
                   "wake up", "stop listening"):
        bridge = _make_bridge()
        bridge._set_state(WakeWordBridge.SLEEPING)
        with patch.object(bridge, "_schedule_close") as mock_close:
            bridge._handle_final(phrase)
            mock_close.assert_not_called(), f"ambient {phrase!r} scheduled close"
        assert bridge.state == WakeWordBridge.SLEEPING, f"ambient {phrase!r} changed state"
        mock_type.assert_not_called()
        mock_exec.assert_not_called()


@patch.object(vb, "type_text")
@patch.object(vb, "press_enter")
@patch.object(vb, "execute_command")
def test_woken_session_payload_is_typed_after_arming(mock_exec, mock_enter, mock_type):
    """'keel continue' (wake word + payload) arms the bridge; "continue" is no
    longer a resume command (Don order 2026-09-24) and types as dictation."""
    bridge = _make_bridge()
    bridge._set_state(WakeWordBridge.SLEEPING)
    bridge._handle_final("keel continue")
    assert bridge.state == WakeWordBridge.ARMED
    mock_type.assert_called_once_with("continue ", interval=0.01)


@patch.object(vb, "type_text")
@patch.object(vb, "press_enter")
@patch.object(vb, "execute_command")
def test_spoken_enter_executes_enter_command(mock_exec, mock_enter, mock_type):
    """'enter' while ARMED presses Enter on demand (replaces auto-Enter)."""
    bridge = _make_bridge()
    bridge._set_state(WakeWordBridge.ARMED)
    bridge._refresh_arm()
    bridge._handle_final("enter")
    mock_exec.assert_called_once_with("enter")
    mock_type.assert_not_called()


def test_resolve_mic_device_validation():
    """mic_device accepts int / digit string / 'default'; anything else -> None."""
    bridge = _make_bridge()
    assert bridge._resolve_mic_device("default") is None
    assert bridge._resolve_mic_device(None) is None
    assert bridge._resolve_mic_device(2) == 2
    assert bridge._resolve_mic_device("3") == 3
    assert bridge._resolve_mic_device(" 4 ") == 4
    # Invalid values fall back to default instead of reaching sounddevice raw.
    assert bridge._resolve_mic_device("USB mic") is None
    assert bridge._resolve_mic_device(1.5) is None


@patch.object(vb, "type_text")
@patch.object(vb, "press_enter")
@patch.object(vb, "execute_command")
def test_long_dictation_types_char_by_char(mock_exec, mock_enter, mock_type):
    """Long dictation still routes to type_text (no paste fast path)."""
    bridge = _make_bridge()
    bridge._dispatch("a paragraph long enough that paste was once considered")
    mock_type.assert_called_once()


@patch("src.intent.log_utterance")
def test_intent_logged_on_dispatcher_thread_not_recv(mock_log):
    """No disk write happens on the recv thread, in the V3 build either.

    The claim this test has always made is unchanged: the AssemblyAI recv
    thread must not do disk work. The V3 surgery points moved WHERE the queue
    boundary sits — `on_transcript` now hands the frame to `_turn_queue`
    (engine/persistence) instead of `_final_queue` (typing), so the durable
    transcript is written before the text can be typed. That is the same
    invariant, enforced one stage earlier, so the assertions are re-pointed at
    the new boundary rather than deleted.
    """
    bridge = _make_bridge()
    bridge._final_queue = MagicMock()
    bridge._turn_queue = MagicMock()
    bridge.on_transcript("hello world", is_final=True)
    # Recv thread: queue only. No intent audit, no typing, no engine write.
    mock_log.assert_not_called()
    bridge._final_queue.put.assert_not_called()
    bridge._turn_queue.put.assert_called_once_with(("hello world", True))

    # A partial is ephemeral: it is queued as (text, False) and never reaches
    # the typing queue. Surfaced as a status preview only.
    bridge._turn_queue.reset_mock()
    bridge.on_transcript("hello wor", is_final=False)
    bridge._turn_queue.put.assert_called_once_with(("hello wor", False))
    bridge._final_queue.put.assert_not_called()

    # The intent audit still runs on the dispatcher thread, with full text.
    bridge._log_utterance("hello world")
    mock_log.assert_called_once_with("hello world")


@patch.object(vb, "type_text")
@patch.object(vb, "press_enter")
@patch.object(vb, "execute_command")
def test_continuous_single_word_command_fires_exact_only(mock_exec, mock_enter, mock_type):
    """Continuous mode: an exact single-word command still executes."""
    bridge = _make_bridge()
    bridge.continuous = True
    bridge.paused = False
    bridge._handle_final("right")
    mock_exec.assert_called_once_with("right")
    mock_type.assert_not_called()


@patch.object(vb, "type_text")
@patch.object(vb, "press_enter")
@patch.object(vb, "execute_command")
def test_continuous_command_word_at_dictation_start_types(mock_exec, mock_enter, mock_type):
    """Continuous mode: a command word at the START of dictation types as text
    (the "Right, if you need me" collision — Don order 2026-09-24)."""
    bridge = _make_bridge()
    bridge.continuous = True
    bridge.paused = False
    bridge._handle_final("right, this is a normal sentence")
    mock_exec.assert_not_called()
    mock_type.assert_called_once_with("right, this is a normal sentence ", interval=0.01)


@patch.object(vb, "type_text")
@patch.object(vb, "press_enter")
@patch.object(vb, "execute_command")
def test_continuous_bare_sleep_pauses(mock_exec, mock_enter, mock_type):
    """Canonical pause command (Don 2026-09-25): exact "sleep" pauses the
    bridge instead of typing."""
    bridge = _make_bridge()
    bridge.continuous = True
    bridge.paused = False
    bridge._handle_final("sleep")
    assert bridge.paused is True
    mock_type.assert_not_called()
    mock_exec.assert_not_called()


@patch.object(vb, "type_text")
@patch.object(vb, "press_enter")
@patch.object(vb, "execute_command")
def test_continuous_sentence_containing_sleep_still_types(mock_exec, mock_enter, mock_type):
    """No prefix matching: "sleep" inside a longer sentence stays dictation
    and must NOT pause the bridge."""
    bridge = _make_bridge()
    bridge.continuous = True
    bridge.paused = False
    bridge._handle_final("Sleep is important.")
    assert bridge.paused is False
    mock_type.assert_called_once_with("Sleep is important. ", interval=0.01)
    mock_exec.assert_not_called()


@patch.object(vb, "type_text")
@patch.object(vb, "press_enter")
@patch.object(vb, "execute_command")
def test_continuous_bare_wake_up_resumes(mock_exec, mock_enter, mock_type):
    """Canonical resume command (Don 2026-09-25): exact "wake up" resumes a
    paused bridge."""
    bridge = _make_bridge()
    bridge.continuous = True
    bridge.paused = True
    bridge._handle_final("wake up")
    assert bridge.paused is False
    mock_type.assert_not_called()
    mock_exec.assert_not_called()


@patch.object(vb, "type_text")
@patch.object(vb, "press_enter")
@patch.object(vb, "execute_command")
def test_continuous_sentence_containing_wake_up_does_not_resume(mock_exec, mock_enter, mock_type):
    """No prefix matching: "wake up the computer tomorrow" stays dictation and
    a paused bridge stays paused."""
    bridge = _make_bridge()
    bridge.continuous = True
    bridge.paused = True
    bridge._handle_final("Wake up the computer tomorrow.")
    assert bridge.paused is True
    mock_type.assert_not_called()
    mock_exec.assert_not_called()


@patch.object(vb, "type_text")
@patch.object(vb, "press_enter")
@patch.object(vb, "execute_command")
def test_continuous_stop_start_listening_are_dictation(mock_exec, mock_enter, mock_type):
    """"stop listening" / "start listening" were REMOVED from the command set
    (Don 2026-09-25) — both type as dictation and neither changes pause state."""
    bridge = _make_bridge()
    bridge.continuous = True
    bridge.paused = False
    bridge._handle_final("stop listening")
    assert bridge.paused is False
    bridge._handle_final("start listening")
    assert bridge.paused is False
    mock_exec.assert_not_called()
    assert [c.args[0] for c in mock_type.call_args_list] == [
        "stop listening ", "start listening "]
