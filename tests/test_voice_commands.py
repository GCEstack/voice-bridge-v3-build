from unittest.mock import patch

from src.voice_commands import handle_command, execute_command


def test_handle_command_recognizes_copy():
    assert handle_command("copy that") == "copy"


def test_handle_command_returns_none_for_plain_text():
    assert handle_command("hello world") is None


def test_handle_command_leading_word_match():
    # Multi-word commands keep leading-word longest-match: "copy that please"
    # still fires, and trailing words are ignored.
    assert handle_command("copy that please") == "copy"
    # "enter" and "up" are single-word triggers — exact-utterance only now.
    # Leading dictation types as text instead of firing the key.
    assert handle_command("enter sandman") is None
    assert handle_command("up the hill") is None


def test_handle_command_exact_matches_still_work():
    assert handle_command("copy that") == "copy"
    assert handle_command("sleep") == "pause"
    # Normalization: case + trailing punctuation still match.
    assert handle_command("Enter!") == "enter"


def test_pause_resume_family_is_exact_and_authorized_language_only():
    # Don order 2026-09-25: canonical pause/resume language is EXACTLY
    # "sleep" (pause) / "wake up" (resume), whole-utterance match only.
    # "stop listening" / "start listening" were REMOVED from the command set
    # and now type as plain dictation.
    assert handle_command("sleep") == "pause"
    assert handle_command("Sleep.") == "pause"
    assert handle_command("wake up") == "resume"
    assert handle_command("Wake up.") == "resume"
    # Removed vocabulary is dictation, not a command.
    for phrase in ("stop listening", "stop listening.", "start listening",
                   "start listening."):
        assert handle_command(phrase) is None
    # No prefix matching: a command word inside a longer sentence is dictation.
    for phrase in ("I need to sleep.", "Sleep is important.",
                   "sleep, rest matters", "I need to wake up tomorrow.",
                   "Wake up the computer tomorrow.", "wake up and go",
                   "voice sleep", "voice wake up", "wake",
                   "resume listening", "continue", "go ahead",
                   "stop listening to the noise", "start listening tomorrow",
                   "continue reading this", "go ahead and say it"):
        assert handle_command(phrase) is None, f"{phrase!r} must type as dictation"
    # Multi-word command words must NOT type as a standalone action by mistake.
    assert handle_command("copy that please") == "copy"


@patch("src.voice_commands.pyautogui.hotkey")
def test_execute_command_copy(mock_hotkey):
    execute_command("copy")
    mock_hotkey.assert_called_once_with("ctrl", "c")


def test_voice_control_triggers_recognized():
    assert handle_command("close window") == "close_window"
    assert handle_command("sleep") == "pause"
    assert handle_command("wake up") == "resume"
    assert handle_command("alt tab") == "alt_tab"
    assert handle_command("command mode") == "command_mode"
    assert handle_command("go back") == "back"


@patch("src.voice_commands.pyautogui.hotkey")
def test_execute_command_save(mock_hotkey):
    execute_command("save")
    mock_hotkey.assert_called_once_with("ctrl", "s")


@patch("src.voice_commands.pyautogui.press")
def test_execute_command_cancel(mock_press):
    execute_command("cancel")
    mock_press.assert_called_once_with("escape")


def test_command_mode_is_a_safe_noop():
    # Stub hook for future voice control — must not raise.
    execute_command("command_mode")


def test_screenshot_phrases_parse():
    assert handle_command("screenshot") == "screenshot"
    assert handle_command("take a screenshot") == "screenshot"
    assert handle_command("take screenshot") == "screenshot"
    assert handle_command("screen capture") == "screenshot"
    assert handle_command("capture screen") == "screenshot"
    # Trailing words still match (leading-word semantics).
    assert handle_command("take a screenshot now") == "screenshot"


@patch("src.voice_commands._screenshot")
def test_execute_command_screenshot(mock_screenshot):
    execute_command("screenshot")
    mock_screenshot.assert_called_once_with()


def test_macro_phrases_parse():
    assert handle_command("proofread") == "macro_proofread"
    assert handle_command("macro proofread") == "macro_proofread"
    assert handle_command("concise") == "macro_concise"
    assert handle_command("make it concise") == "macro_concise"
    assert handle_command("format") == "macro_format"
    assert handle_command("make it professional") == "macro_format"


@patch("src.voice_commands._macro")
def test_execute_command_macros(mock_macro):
    execute_command("macro_proofread")
    execute_command("macro_concise")
    execute_command("macro_format")
    assert mock_macro.call_args_list[0][0][0] == "proofread"
    assert mock_macro.call_args_list[1][0][0] == "concise"
    assert mock_macro.call_args_list[2][0][0] == "format"


def test_cockpit_phrases_parse():
    assert handle_command("start cockpit") == "start_cockpit"
    assert handle_command("open cockpit") == "start_cockpit"
    assert handle_command("launch cockpit") == "start_cockpit"
    assert handle_command("cockpit") == "start_cockpit"
    assert handle_command("cockpit please") is None  # single-word trigger: exact only
    # Mid-utterance mention types as text (leading-word semantics).
    assert handle_command("the cockpit is nice") is None


@patch("src.voice_commands.os.startfile")
def test_execute_command_start_cockpit(mock_startfile):
    from src.voice_commands import COCKPIT_LAUNCHER
    execute_command("start_cockpit")
    mock_startfile.assert_called_once_with(COCKPIT_LAUNCHER)


def test_handoff_phrases_parse():
    assert handle_command("start handoff") == "start_handoff"
    assert handle_command("open handoff") == "start_handoff"
    assert handle_command("new handoff") == "start_handoff"
    assert handle_command("handoff") == "start_handoff"
    # Mid-utterance mention types as text (leading-word semantics).
    assert handle_command("the handoff was clean") is None


@patch("src.voice_commands.os.startfile")
def test_execute_command_start_handoff(mock_startfile):
    from src.voice_commands import HANDOFF_LAUNCHER
    execute_command("start_handoff")
    mock_startfile.assert_called_once_with(HANDOFF_LAUNCHER)


def test_delete_phrases_parse():
    assert handle_command("delete") == "delete"
    assert handle_command("delete that") == "delete"
    assert handle_command("delete all") == "clear"
    assert handle_command("clear all") == "clear"
    assert handle_command("backspace") == "backspace"


def test_comma_separated_commands_still_match():
    # Mid-utterance comma must not break the leading-word match for
    # multi-word commands.
    assert handle_command("select all, delete") == "select_all"
    # A comma-separated repeat of a SINGLE-WORD trigger types as dictation —
    # "delete" is exact-utterance only (Don order 2026-09-24).
    assert handle_command("delete, delete") is None


def test_decimal_tokens_survive_punctuation_strip():
    assert handle_command("kimi 2.7 a") == "window_a"


@patch("src.voice_commands._focused_is_terminal", return_value=False)
@patch("src.voice_commands.pyautogui.press")
def test_execute_command_delete_presses_delete(mock_press, _is_term):
    execute_command("delete")
    mock_press.assert_called_once_with("delete")


@patch("src.voice_commands.pyautogui.press")
def test_execute_command_backspace_presses_backspace(mock_press):
    execute_command("backspace")
    mock_press.assert_called_once_with("backspace")


@patch("src.voice_commands._focused_is_terminal", return_value=False)
@patch("src.voice_commands.pyautogui.hotkey")
@patch("src.voice_commands.pyautogui.press")
def test_execute_command_clear_selects_all_then_deletes(mock_press, mock_hotkey, _is_term):
    execute_command("clear")
    mock_hotkey.assert_called_once_with("ctrl", "a")
    mock_press.assert_called_once_with("delete")


@patch("src.voice_commands._focused_is_terminal", return_value=True)
@patch("src.voice_commands.pyautogui.hotkey")
@patch("src.voice_commands.pyautogui.press")
def test_execute_command_clear_in_terminal_wipes_line(mock_press, mock_hotkey, _is_term):
    execute_command("clear")
    mock_hotkey.assert_called_once_with("ctrl", "up")
    mock_press.assert_not_called()


@patch("src.voice_commands._focused_is_terminal", return_value=True)
@patch("src.voice_commands.pyautogui.hotkey")
@patch("src.voice_commands.pyautogui.press")
def test_execute_command_delete_in_terminal_wipes_line(mock_press, mock_hotkey, _is_term):
    execute_command("delete")
    mock_hotkey.assert_called_once_with("ctrl", "up")
    mock_press.assert_not_called()


def test_numbered_navigation_parses():
    assert handle_command("window one") == "window_1"
    assert handle_command("window 1") == "window_1"
    assert handle_command("terminal three") == "terminal_3"
    assert handle_command("terminal 3") == "terminal_3"
    assert handle_command("screen two") == "screen_2"
    assert handle_command("screen 2") == "screen_2"


def test_list_windows_phrases_parse():
    assert handle_command("windows") == "list_windows"
    assert handle_command("who") == "list_windows"
    assert handle_command("list windows") == "list_windows"


def test_devpad_number_phrases_parse():
    # Stable DevPad tile address — words and digits resolve to the same tile.
    assert handle_command("number one") == "devpad_1"
    assert handle_command("number 1") == "devpad_1"
    assert handle_command("focus number three") == "devpad_3"
    assert handle_command("focus number 3") == "devpad_3"
    assert handle_command("open number seven") == "devpad_7"
    assert handle_command("open number 7") == "devpad_7"
    assert handle_command("number 9") == "devpad_9"
    # Deterministic-phrase only: bare numbers and mid-utterance mentions must
    # NOT fire (dictation safety), and trailing words still match (leading-word).
    assert handle_command("three") is None
    assert handle_command("the number 3 is important") is None
    assert handle_command("number seven please") == "devpad_7"


@patch("src.voice_commands._activate_app_window")
def test_execute_command_window_number(mock_act):
    execute_command("window_2")
    mock_act.assert_called_once_with(2)


@patch("src.voice_commands._activate_terminal_window")
def test_execute_command_terminal_number(mock_act):
    execute_command("terminal_3")
    mock_act.assert_called_once_with(3)


@patch("src.voice_commands._move_to_monitor")
def test_execute_command_screen_number(mock_move):
    execute_command("screen_2")
    mock_move.assert_called_once_with(2)


@patch("src.voice_commands._focus_devpad_tile")
def test_execute_command_devpad_number(mock_focus):
    execute_command("devpad_5")
    mock_focus.assert_called_once_with(5)
    execute_command("devpad_9")
    mock_focus.assert_called_with(9)


@patch("src.voice_commands._window_map", return_value=["1. A", "2. B"])
def test_execute_command_list_windows(mock_map):
    assert execute_command("list_windows") == "1. A | 2. B"


def test_single_word_commands_fire_only_on_exact_utterance():
    # Don order 2026-09-24 (Rule A): every single-word trigger fires ONLY when
    # the whole utterance IS that word. Normalization still handles case and
    # edge punctuation.
    command_map = {
        "right": "right",
        "left": "left",
        "up": "up",
        "down": "down",
        "enter": "enter",
        "send": "enter",
        "space": "space",
        "save": "save",
        "copy": "copy",
        "quote": "quote",
        "who": "list_windows",
        "windows": "list_windows",
    }
    for utt, action in command_map.items():
        assert handle_command(utt) == action
        assert handle_command(utt + ".") == action
        assert handle_command(utt.title()) == action
    # Same single words at the START of dictation (Rule B — Luce's collision
    # family) must NOT fire a command; they type as plain text.
    beginning_collisions = [
        "right, if you need me",
        "up in the morning",
        "down the street",
        "left on the shelf",
        "enter the building",
        "send the file",
        "space is big",
        "save the document",
        "copy the notes",
        "quote from the document",
        "who is calling",
    ]
    for utt in beginning_collisions:
        assert handle_command(utt) is None, f"{utt!r} must type as dictation"
