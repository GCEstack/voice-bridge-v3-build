"""Voice command parser and executor — migrated from the old EPO Command Center
voice_access.py command set. Speaks a much bigger vocabulary than the original
bridge: session control, text editing, clipboard, nav/punctuation, caps,
deletion (word/line/sentence), terminal switching (a/b/c/d, next/prev), and
monitor-screen moves.

Matching semantics (Don order 2026-09-24). Deliberate multi-word commands
keep the historical leading-word, longest-match-first rule: "copy that" wins
over "copy", trailing words still match ("copy that please"), and "copythis"
/ "command" don't trigger wrong commands. SINGLE-WORD triggers are now
EXACT-utterance only — "enter", "right", "save", "copy" fire only when the
whole utterance IS that word, so dictation like "enter the building" or
"right, if you need me" types instead of pressing a key. The pause/resume
family is STANDALONE-ONLY (whole-utterance equality) and its canonical
language is exactly "sleep" (pause) / "wake up" (resume), Don order
2026-09-25. "stop listening" / "start listening" are REMOVED from the command
set and now type as dictation. A false pause disables the whole bridge until
a resume phrase, and every other misroute just types wrong text.
"""

import os
import re
import sys
import threading
import time
import json

try:
    import pyautogui
    pyautogui.FAILSAFE = False  # voice users may leave the cursor in a corner
except ImportError:
    pyautogui = None  # type: ignore[assignment]

try:
    from src.keyboard_input import type_text as _kb_type_text
except ImportError:
    _kb_type_text = None  # type: ignore[assignment]

try:
    from src.keyboard_input import target_window_title as _target_window_title
except ImportError:
    _target_window_title = None  # type: ignore[assignment]

try:
    from src.keyboard_input import target_window_class as _target_window_class
except ImportError:
    _target_window_class = None  # type: ignore[assignment]

try:
    from src.keyboard_input import restore_target_window as _restore_target_window
except ImportError:
    _restore_target_window = None  # type: ignore[assignment]

# Reconnect is bridged back to the VoiceBridge control window (single
# implementation: WakeWordBridge._reconnect_now). Voice routes set this hook.
_RECONNECT_CALLBACK = None

_FOCUS_LABELS = {
    "focus_luce": "Luce",
    "focus_talon": "Talon",
    "focus_coda": "Coda",
    "focus_devpad": "DevPad",
    "focus_opencode": "OpenCode",
    "focus_voicebridge": "VoiceBridge",
}

# Stable DevPad tile address (config `tileId`): NUMBER != SEAT != MODEL != RUNTIME.
# The board position / Don-approved config owns the number; it never renumbers on
# model, pid, availability, or launch order. 1..9 = row-major Coda..Falcon.
_DEVPAD_CONTROL_URL = "http://localhost:4727"


def _focus_devpad_tile(number: int) -> bool:
    """Focus/activate DevPad tile ``number`` via the DevPad control API.

    The DevPad adapter picks the OS action per surface: browser seats raise their
    real window; opencode/service seats register the activation (their pty lives
    in the DevPad browser window, so non-browser tiles additionally raise the
    board window best-effort). Does NOT invent new lifecycle semantics for a tile
    whose runtime is not started — existing DevPad focus behavior applies.
    """
    if not (1 <= number <= 9):
        return False
    import urllib.request
    base = _DEVPAD_CONTROL_URL
    try:
        surface = ""
        with urllib.request.urlopen(f"{base}/api/seats/{number}", timeout=5) as r:
            try:
                surface = ((json.loads(r.read().decode("utf-8", "replace")).get("state") or {}).get("surface") or "").lower()
            except Exception:
                surface = ""
        req = urllib.request.Request(f"{base}/api/seats/{number}/focus", method="POST")
        with urllib.request.urlopen(req, timeout=10) as r2:
            ok = r2.status == 200
        if surface and surface != "browser":
            _focus_named_window("DevPad")
        return ok
    except Exception:
        return False


def set_reconnect_callback(fn) -> None:
    global _RECONNECT_CALLBACK
    _RECONNECT_CALLBACK = fn


def _trigger_reconnect() -> None:
    if _RECONNECT_CALLBACK is not None:
        try:
            _RECONNECT_CALLBACK()
        except Exception:
            pass


_COMMANDS = {
    # --- Session control -----------------------------------------------
    # Canonical pause/resume language is EXACTLY "sleep" / "wake up"
    # (Don order 2026-09-25): short, natural voice controls. Whole-utterance
    # equality only — never prefix/leading-word matching, so "I need to sleep"
    # and "wake up the computer tomorrow" stay dictation. The previous
    # vocabulary ("stop listening" / "start listening") is REMOVED from the
    # command set and now types as plain dictation, as do every other former
    # alias ("voice sleep", "wake", "resume listening", "continue",
    # "go ahead"). The family is STANDALONE-ONLY (whole-utterance equality) —
    # see _STANDALONE_ONLY_ACTIONS below.
    "sleep": "pause",
    "wake up": "resume",
    "quit": "quit",
    "exit": "quit",

    # --- Text editing ----------------------------------------------------
    "new line": "newline",
    "next line": "newline",
    "delete all": "clear",
    "delete that": "delete",
    "delete": "delete",
    "delete up": "delete_up",
    "delete word": "delete_word",
    "remove word": "delete_word",
    "delete line": "delete_line",
    "delete sentence": "delete_sentence",
    "backspace": "backspace",
    "backspace that": "backspace",
    "clear all": "clear",
    "select all": "select_all",
    "select everything": "select_all",
    "undo": "undo",
    "undo that": "undo",
    "redo": "redo",
    "cut": "cut",
    "cut that": "cut",
    "copy": "copy",
    "copy that": "copy",
    "paste": "paste",
    "paste it": "paste",
    "save": "save",
    "save it": "save",

    # --- Punctuation -----------------------------------------------------
    "period": "period",
    "comma": "comma",
    "question mark": "question_mark",
    "exclamation mark": "exclamation_mark",
    "quote": "quote",
    "apostrophe": "apostrophe",
    "colon": "colon",
    "semicolon": "semicolon",
    "tab": "tab",
    "space": "space",

    # --- Messaging --------------------------------------------------------
    "send": "enter",
    "send message": "enter",
    "send it": "enter",
    "enter": "enter",
    "return": "enter",
    "new paragraph": "enter",

    # --- Caps lock ---------------------------------------------------------
    "caps on": "caps_on",
    "caps lock on": "caps_on",
    "caps off": "caps_off",
    "caps lock off": "caps_off",

    # --- Navigation ---------------------------------------------------------
    "up": "up",
    "go up": "up",
    "down": "down",
    "go down": "down",
    "left": "left",
    "go left": "left",
    "right": "right",
    "go right": "right",
    "page up": "page_up",
    "page down": "page_down",

    # --- Window / tabs ------------------------------------------------------
    "switch window": "switch_window",
    "next window": "switch_window",
    "next terminal": "switch_window",
    "previous window": "previous_window",
    "previous terminal": "previous_window",
    "close tab": "close_tab",
    "new tab": "new_tab",
    "new window": "new_window",
    "reopen tab": "reopen_tab",
    "close window": "close_window",
    "minimize": "minimize",
    "maximize": "maximize",
    "show desktop": "show_desktop",
    "task view": "task_view",
    "go back": "back",
    "go forward": "forward",
    "refresh": "refresh",
    "reload": "refresh",
    "find": "find",
    "search page": "find",
    "zoom in": "zoom_in",
    "zoom out": "zoom_out",
    "cancel that": "cancel",
    "never mind": "cancel",
    "dismiss": "cancel",
    "alt tab": "alt_tab",
    "command mode": "command_mode",

    # --- Terminal windows a/b/c/d (Kimi terminals #8a-#8d) ----------------
    "window a": "window_a",
    "terminal a": "window_a",
    "terminal eight": "window_a",
    "terminal 8": "window_a",
    "eight a": "window_a",
    "kimi eight a": "window_a",
    "kimi 2.7 a": "window_a",
    "kimi 2.7 eight a": "window_a",
    "window b": "window_b",
    "terminal b": "window_b",
    "eight b": "window_b",
    "kimi eight b": "window_b",
    "kimi 2.7 b": "window_b",
    "kimi 2.7 eight b": "window_b",
    "window c": "window_c",
    "terminal c": "window_c",
    "eight c": "window_c",
    "kimi eight c": "window_c",
    "kimi 2.7 c": "window_c",
    "kimi 2.7 eight c": "window_c",
    "window d": "window_d",
    "terminal d": "window_d",
    "eight d": "window_d",
    "kimi eight d": "window_d",
    "kimi 2.7 d": "window_d",
    "kimi 2.7 eight d": "window_d",

    "screenshot": "screenshot",
    "take a screenshot": "screenshot",
    "take screenshot": "screenshot",
    "screen capture": "screenshot",
    "capture screen": "screenshot",

    # --- App launch (operator seat + handoff) ----------------------------
    "start cockpit": "start_cockpit",
    "open cockpit": "start_cockpit",
    "launch cockpit": "start_cockpit",
    "cockpit": "start_cockpit",
    "start handoff": "start_handoff",
    "open handoff": "start_handoff",
    "new handoff": "start_handoff",
    "handoff": "start_handoff",

    # --- Named window focus (seat windows by title) ----------------------
    "go to luce": "focus_luce",
    "go to talon": "focus_talon",
    "go to coda": "focus_coda",
    "go to devpad": "focus_devpad",
    "go to opencode": "focus_opencode",
    "go to voicebridge": "focus_voicebridge",

    # --- Reconnect (bridged to the VoiceBridge control window) -----------
    "reconnect": "reconnect",

    # --- AI text macros (proofread / concise / format) -------------------
    "proofread": "macro_proofread",
    "proofread this": "macro_proofread",
    "proof read": "macro_proofread",
    "macro proofread": "macro_proofread",
    "concise": "macro_concise",
    "make it concise": "macro_concise",
    "format": "macro_format",
    "format this": "macro_format",
    "format it": "macro_format",
    "professional": "macro_format",
    "make it professional": "macro_format",

    # --- Monitors / screens (numbered left→right; screen N added below) ----
    "main screen": "screen_1",
    "main laptop": "screen_1",
    "laptop": "screen_1",
    "jump left": "screen_1",
    "jump to laptop": "screen_1",
    "middle screen": "screen_2",
    "jump center": "screen_2",
    "jump middle": "screen_2",
    "hp": "screen_3",
    "hp monitor": "screen_3",
    "jump right": "screen_3",
    "jump to hp": "screen_3",

    # --- Window registry ---------------------------------------------------
    "list windows": "list_windows",
    "what windows": "list_windows",
    "windows": "list_windows",
    "who": "list_windows",
}

# Numbered navigation: "window N" / "terminal N" / "screen N", words or digits.
# window N  -> Nth app window by open order (renumbers as windows close)
# terminal N -> Nth terminal window
# screen N   -> Nth monitor, left→right
# number N / focus number N / open number N -> STABLE DevPad tile address
#   (config `tileId`; NEVER model/pid/launch order). Bare "one".."nine" are NOT
#   commands — deterministic phrases only, so dictation stays safe.
_NUMBER_WORDS = (
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
)
for _i, _word in enumerate(_NUMBER_WORDS, 1):
    _COMMANDS[f"window {_word}"] = f"window_{_i}"
    _COMMANDS[f"window {_i}"] = f"window_{_i}"
    _COMMANDS[f"terminal {_word}"] = f"terminal_{_i}"
    _COMMANDS[f"terminal {_i}"] = f"terminal_{_i}"
    _COMMANDS[f"screen {_word}"] = f"screen_{_i}"
    _COMMANDS[f"screen {_i}"] = f"screen_{_i}"
    _COMMANDS[f"number {_word}"] = f"devpad_{_i}"
    _COMMANDS[f"number {_i}"] = f"devpad_{_i}"
    _COMMANDS[f"focus number {_word}"] = f"devpad_{_i}"
    _COMMANDS[f"focus number {_i}"] = f"devpad_{_i}"
    _COMMANDS[f"open number {_word}"] = f"devpad_{_i}"
    _COMMANDS[f"open number {_i}"] = f"devpad_{_i}"

# Standalone-only command family (pause/resume). A false pause disables the
# whole bridge until a resume phrase — worse than mis-typed dictation — so
# these fire ONLY when the entire utterance equals the phrase (word-boundary
# via per-token equality). Authorized language is exactly "sleep" (pause) /
# "wake up" (resume) (Don order 2026-09-25); every other candidate phrase is
# absent from _COMMANDS so it types as dictation. All other families keep
# leading-word matching, with single-word triggers exact-utterance only.
_STANDALONE_ONLY_ACTIONS = {"pause", "resume"}
_STANDALONE_PHRASES = {
    phrase: action
    for phrase, action in _COMMANDS.items()
    if action in _STANDALONE_ONLY_ACTIONS
}


COMMAND_HELP = """\
VOICE COMMANDS:
  "sleep"               - pause dictation (mic on, won't type)  [whole utterance only]
  "wake up"             - resume dictation                      [whole utterance only]
  "quit" / "exit"       - stop the program

  "new line"            - press Enter
  "delete"              - wipes selection (Delete); in a terminal, wipes the line (Ctrl+Up)
  "delete all"          - Ctrl+A then Delete; in a terminal, wipes the line (Ctrl+Up)
  "clear all"           - same as delete all
  "select all"          - Ctrl+A
  "delete word"         - Ctrl+Backspace
  "delete line"         - select line + Delete
  "delete sentence"     - select sentence + Delete
  "delete up"           - Ctrl+Up (legacy PowerShell line delete)
  "backspace"           - Backspace key
  "copy" / "copy that"  - Ctrl+C
  "paste" / "paste it"  - Ctrl+V
  "cut" / "cut that"    - Ctrl+X
  "undo" / "redo"       - Ctrl+Z / Ctrl+Y
  "save" / "save it"    - Ctrl+S
  "close" / "close window" - Alt+F4
  "send" / "enter" / "return" - press Enter

  "caps on" / "caps off" - toggle Caps Lock
  "tab" / "space"        - Tab / Space
  "period" / "comma" / "question mark" / "exclamation mark"
  "quote" / "apostrophe" / "colon" / "semicolon"

  "up" / "down" / "left" / "right" - arrow keys
  "page up" / "page down"

  "switch window" / "next terminal" - cycle next terminal
  "previous window" / "previous terminal" - cycle back
  "window a/b/c/d"       - jump to terminal #1-#4
  "close tab" / "new tab" - Ctrl+W / Ctrl+T
  "minimize" / "maximize"

  "window N"             - focus Nth window (open order; renumbers on close)
  "terminal N"           - focus Nth terminal window
  "screen N"             - move the window to Nth monitor (left -> right)
  "windows" / "who"      - print the live window map
  "number N" / "focus number N" / "open number N" - focus DevPad tile N
                         (STABLE board address: 1 Coda, 2 Chiave, 3 Vittorio,
                          4 Nico, 5 VoiceBridge, 6 Luce, 7 Talon, 8 Keel,
                          9 Falcon. Never renumbers with model/pid/order.)

  "main laptop" / "screen 1" / "jump left"  - leftmost monitor
  "middle screen" / "screen 2" / "jump center" - second monitor
  "hp" / "screen 3" / "jump right" - rightmost monitor

  "screenshot" / "take a screenshot" - capture full desktop to clipboard
  "cockpit" / "start cockpit"  - launch the operator seat
  "handoff" / "start handoff"  - new window: requirements -> architecture -> Kimi

  "proofread"      - fix grammar/spelling on the selected text (AI)
  "concise"        - rewrite the selected text shorter (AI)
  "format"         - rewrite the selected text as professional/formal (AI)
"""


def handle_command(text: str) -> str | None:
    """Return the action token if the utterance matches a command phrase.

    Matching rule (Don order 2026-09-25 for the pause/resume family; 2026-09-24
    for everything else):
    - Standalone-only family (pause/resume): the ENTIRE utterance must equal
      the phrase after case/whitespace/punctuation normalization. The ONLY
      authorized phrases are "sleep" (pause) and "wake up" (resume).
      "stop listening" / "start listening" were REMOVED and type as
      dictation. Prefix matching is deliberately NOT used, so "I need to
      sleep." and "wake up the computer tomorrow." stay dictation.
    - SINGLE-WORD triggers (right/left/up/down/enter/send/save/copy/quote/
      who/space/delete/...): the ENTIRE utterance must equal that word — a
      leading-word match would let dictation like "right, if you need me" or
      "save the document" fire a destructive keypress.
    - Multi-word commands keep the longest-match-first leading-word rule:
      "copy that" beats "copy", and trailing words still match ("format this
      paragraph").
    """
    # Strip punctuation per token so an internal comma/period does not break
    # the match (e.g. "select all, delete" -> ["select","all","delete"]).
    # Only edge punctuation is removed, so tokens like "2.7" stay intact.
    words = [w.strip(".,;:!?") for w in text.lower().strip().split()]
    words = [w for w in words if w]
    if not words:
        return None
    # 1) Standalone-only family (pause/resume): whole-utterance equality.
    for action, phrase in sorted(
        ((a, p) for p, a in _STANDALONE_PHRASES.items()),
        key=lambda pa: len(pa[1]),
        reverse=True,
    ):
        if words == phrase.split():
            return action
    # 2) Everything else, longest-match-first. Single-word triggers are
    #    exact-utterance only (dictation safety); multi-word phrases keep the
    #    leading-word rule so "copy that" + trailing words still fires.
    for phrase in sorted(
        (p for p in _COMMANDS if p not in _STANDALONE_PHRASES),
        key=len,
        reverse=True,
    ):
        phrase_words = phrase.split()
        if len(words) < len(phrase_words):
            continue
        if words[:len(phrase_words)] == phrase_words and (
            len(phrase_words) > 1 or len(words) == len(phrase_words)
        ):
            return _COMMANDS[phrase]
    return None


def _type_text(text: str) -> None:
    # Same backend as dictation (keyboard.write) so non-ASCII is typed.
    if _kb_type_text is not None:
        _kb_type_text(text)


def _hotkey(*keys: str) -> None:
    # Send to the same window dictation targets, not whatever happens to hold
    # focus (the always-on-top VoiceBridge window can otherwise steal it).
    if _restore_target_window is not None:
        try:
            _restore_target_window()
        except Exception:
            pass
    if pyautogui is not None:
        try:
            pyautogui.hotkey(*keys)
        except Exception:
            pass


def _press(key: str) -> None:
    if _restore_target_window is not None:
        try:
            _restore_target_window()
        except Exception:
            pass
    if pyautogui is not None:
        try:
            pyautogui.press(key)
        except Exception:
            pass


def _screenshot() -> None:
    # Captures the full desktop and puts it on the clipboard for pasting.
    try:
        from src.screenshot import screenshot_to_clipboard
        screenshot_to_clipboard(all_screens=True)
    except Exception:
        pass


# Operator-seat launchers — one path each, shared by voice commands and the
# main-window Cockpit button (voice_bridge reuses execute_command).
COCKPIT_LAUNCHER = r"C:\Users\Dekan AI Brother\GCE_DON\cockpit\START-COCKPIT.cmd"

# DISCONNECTED 2026-10-03 (Nico, Don ruling for the queue plumbing reset).
#   The voice phrases "handoff" / "start handoff" / "open handoff" / "new handoff"
#   used to launch the superseded 03_HANDOFFS UI. That surface is now ARCHIVED
#   and must never be reachable by voice again, so the launcher path and the
#   command handler are both gone rather than pointed somewhere else.
#   Replacement for the real need: the queue panel's HANDOFF button, which
#   produces a payload from a queued result and archives the source.
#   The archived copy: GCE_ARCHIVE\2026-10-03_LEGACY_ROUTING_HANDOFF_LEDGER_PRE_RESET\03_HANDOFFS
HANDOFF_DISCONNECTED = (
    "handoff is no longer a voice command. Use the VoiceBridge queue panel: "
    "select an item and press HANDOFF."
)

# --- seat vocabulary: registry-driven, MODEL != SEAT (2026-09-25) -----------
# Window-title matching must never resolve a MODEL, a retired seat or a HOLD
# name to a seat. The single machine authority is the seat registry; the literal
# below is only a fallback for the case where the registry is unreadable, and it
# deliberately omits every retired / HOLD / non-seat token.
SEAT_REGISTRY_PATH = (
    r"C:\Users\Dekan AI Brother\GCE_ORG\01_STRATEGIC_FRAMEWORK"
    r"\Naming_Identity\seat_registry.json"
)
_FALLBACK_SEATS = (
    "talon", "luce", "keel", "coda", "corrado",
    "vittorio", "nico", "magpie", "pigeon",
    "falcon", "raven", "ragno", "chiave",
)


def _seat_keywords() -> tuple:
    """Active registry seat names, lowercased, for window-title matching.

    Retired seats (Kimi, Calibro) and HOLD names (GLM, Kimi_Plumb) are NOT seats
    and are excluded by construction. MODEL != SEAT: no model, provider or
    runtime token is ever returned as a seat.
    """
    try:
        with open(SEAT_REGISTRY_PATH, "r", encoding="utf-8-sig") as fh:
            reg = json.load(fh)
        seats = [s for s in reg.get("seats", []) if s.get("loadable")]
        keys = tuple(sorted({str(s["seat"]).lower() for s in seats if s.get("seat")}))
        if keys:
            return keys
    except Exception:
        pass
    return _FALLBACK_SEATS


def _launch_cmd(path: str) -> None:
    # os.startfile = ShellExecute: detached launch, no console steal.
    try:
        os.startfile(path)  # type: ignore[attr-defined]
    except Exception:
        pass


def _start_cockpit() -> None:
    _launch_cmd(COCKPIT_LAUNCHER)


def _start_handoff() -> None:
    """DISCONNECTED 2026-10-03. Kept as a name so nothing raises NameError.

    Saying "handoff" now reports the retirement instead of launching the
    archived 03_HANDOFFS UI. It must never launch that surface again.
    """
    print(HANDOFF_DISCONNECTED)
    return HANDOFF_DISCONNECTED


def _log_delta(mode: str, original: str, result: str) -> None:
    """Append a word-level delta report (original vs rewritten) to proofread_deltas.log."""
    import datetime
    import difflib
    import os
    a = original.split()
    b = result.split()
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    changes = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        removed = " ".join(a[i1:i2])
        added = " ".join(b[j1:j2])
        if tag == "replace":
            changes.append(f"  '{removed}' -> '{added}'")
        elif tag == "delete":
            changes.append(f"  REMOVED '{removed}'")
        elif tag == "insert":
            changes.append(f"  ADDED '{added}'")
    if not changes:
        return
    pct = abs(len(a) - len(b)) / max(len(a), len(b), 1)
    flag = "  *** LARGE CHANGE — review ***" if pct > 0.30 else ""
    entry = [
        f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {mode} "
        f"({len(original)} -> {len(result)} chars, {len(a)} -> {len(b)} words)",
        *changes,
        flag if flag else "",
        "-" * 60,
    ]
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "proofread_deltas.log")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(entry) + "\n")


def _macro(mode: str) -> None:
    # select all -> copy -> LLM rewrite -> reselect -> paste.
    _hotkey("ctrl", "a")
    time.sleep(0.1)
    _hotkey("ctrl", "c")
    time.sleep(0.15)
    try:
        import pyperclip
        text = pyperclip.paste()
    except Exception:
        return
    if not text or not text.strip():
        return
    try:
        from src.llm import rewrite_text
        result = rewrite_text(mode, text.strip())
    except Exception:
        return
    if not result:
        return
    try:
        _log_delta(mode, text.strip(), result)
    except Exception:
        pass
    try:
        import pyperclip
        pyperclip.copy(result)
    except Exception:
        return
    time.sleep(0.1)
    _hotkey("ctrl", "a")
    time.sleep(0.1)
    _hotkey("ctrl", "v")


# ---------------------------------------------------------------------------
# Window focus helpers (Windows-only) — ported from voice_access.py
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsIconic.argtypes = [wintypes.HWND]
    _user32.IsIconic.restype = wintypes.BOOL
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextLengthW.restype = wintypes.INT
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, wintypes.INT]
    _user32.GetWindowTextW.restype = wintypes.INT

    _LAST_FOREGROUND_HWND = None

    def _list_visible_windows() -> list[tuple[object, str]]:
        results = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _enum(hwnd, _):
            if not _user32.IsWindowVisible(hwnd):
                return True
            length = _user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            if title:
                results.append((hwnd, title))
            return True

        _user32.EnumWindows(_enum, 0)
        return results

    def _is_terminal_window(title: str) -> bool:
        lower = title.lower()
        return any(k in lower for k in (
            "cmd.exe", "powershell", "kimi", "windows terminal", "wt.exe",
        ))

    # Window classes that are always a console/terminal, regardless of title.
    _TERMINAL_CLASSES = {
        "consolewindowclass",             # conhost: cmd.exe, legacy PowerShell
        "cascadia_hosting_window_class",  # Windows Terminal
        "mintty",                         # Git Bash
        "virtualconsole",                 # ConEmu
    }

    def _focused_is_terminal() -> bool:
        """True if the remembered target window is a terminal.

        Class check first (reliable), then title keywords as a fallback.
        """
        try:
            if _target_window_class is not None:
                cls = (_target_window_class() or "").strip().lower()
                if cls in _TERMINAL_CLASSES:
                    return True
            if _target_window_title is not None:
                return _is_terminal_window(_target_window_title() or "")
        except Exception:
            pass
        return False

    _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, wintypes.INT]
    _user32.GetClassNameW.restype = wintypes.INT
    _user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
    ]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    _kernel32 = ctypes.windll.kernel32

    class _FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    def _process_start_time(pid: int) -> int:
        """Process creation time as a comparable int (0 if unknown)."""
        h = _kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not h:
            return 0
        try:
            creation, exit_t, kern_t, user_t = (
                _FILETIME(), _FILETIME(), _FILETIME(), _FILETIME()
            )
            ok = _kernel32.GetProcessTimes(
                h, ctypes.byref(creation), ctypes.byref(exit_t),
                ctypes.byref(kern_t), ctypes.byref(user_t),
            )
            if not ok:
                return 0
            return (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        finally:
            _kernel32.CloseHandle(h)

    # Shell/OS windows that are not "apps" the operator navigates to.
    _EXCLUDED_CLASSES = {
        "progman", "workerw", "shell_traywnd",
        "windows.ui.core.corewindow", "windows.ui.core.corewindow",
    }
    _EXCLUDED_TITLES = {"program manager", "windows input experience", "settings"}
    _SELF_TITLE = "voicebridge"

    def _enumerate_app_windows() -> list[dict]:
        """Top-level app windows, filtered, sorted by OPEN ORDER (process start).

        Renumbering is implicit: the list is rebuilt on every call, so when a
        window closes the numbers compact back to 1..N.
        """
        rows: list[dict] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _enum(hwnd, _):
            if not _user32.IsWindowVisible(hwnd):
                return True
            length = _user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            tb = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, tb, length + 1)
            title = tb.value
            if not title:
                return True
            cbuf = ctypes.create_unicode_buffer(256)
            _user32.GetClassNameW(hwnd, cbuf, 256)
            cls = cbuf.value
            pid = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            low = title.strip().lower()
            if cls.lower() in _EXCLUDED_CLASSES:
                return True
            if low in _EXCLUDED_TITLES:
                return True
            if low == _SELF_TITLE and pid.value == os.getpid():
                return True
            rows.append({
                "hwnd": hwnd,
                "title": title,
                "class": cls,
                "pid": pid.value,
                "created": _process_start_time(pid.value),
            })
            return True

        _user32.EnumWindows(_enum, 0)
        rows.sort(key=lambda w: (w["created"] or (1 << 62), w["title"].lower()))
        return rows

    # Registry-driven (2026-09-25): seat-keyword vocabulary comes from
    # seat_registry.json — the single machine authority. magpie/pigeon appear
    # here as seat vocabulary but get NO panes, NO mailboxes, NO mailroom keys,
    # NO ai-inbox folders (GCE Frozen Seat Migration 2026-09-22, ruling 8).
    # REMOVED: "calibro" (seat retired -> Nico), "kimi" (seat retired 2026-09-22),
    # "glm" (HOLD name). Those are not seats and must never be resolved to one.
    _SEAT_KEYWORDS = _seat_keywords()

    # Seat names are matched as whole words so a browser tab titled
    # "... Kimi docs ..." is not mistaken for the seat window "Kimi".
    _SEAT_RE = re.compile(
        r"\b(" + "|".join(_SEAT_KEYWORDS) + r")\b", re.IGNORECASE
    )

    def _seat_for_title(title: str) -> str | None:
        m = _SEAT_RE.search(title or "")
        return m.group(1).capitalize() if m else None

    def _seat_windows() -> list[dict]:
        """Only windows that carry a seat identity, in open order."""
        return [w for w in _enumerate_app_windows() if _seat_for_title(w["title"])]

    def _window_map() -> list[str]:
        lines = []
        for i, w in enumerate(_seat_windows(), 1):
            lines.append(f"window {i}: {w['title']} [{_seat_for_title(w['title'])}]")
        for i, w in enumerate(_terminal_windows(), 1):
            lines.append(f"terminal {i}: {w['title']}")
        return lines

    def _activate_app_window(number: int) -> bool:
        windows = _seat_windows()
        idx = number - 1
        if idx < 0 or idx >= len(windows):
            return False
        return _activate_window(windows[idx]["hwnd"])

    def _activate_terminal_window(number: int) -> bool:
        terminals = [
            w for w in _enumerate_app_windows()
            if w["class"].lower() in _TERMINAL_CLASSES
        ]
        idx = number - 1
        if idx < 0 or idx >= len(terminals):
            return False
        return _activate_window(terminals[idx]["hwnd"])

    def _activate_seat(seat: str) -> bool:
        wanted = (seat or "").strip().lower()
        for w in _enumerate_app_windows():
            if wanted and wanted in w["title"].lower():
                return _activate_window(w["hwnd"])
        return False

    def _monitors() -> list[tuple[int, int, int, int]]:
        """Monitor work areas as (left, top, right, bottom), sorted left→right."""
        MONITORENUMPROC = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
            ctypes.POINTER(wintypes.RECT), wintypes.LPARAM,
        )
        rects: list[tuple[int, int, int, int]] = []

        def _cb(hmon, hdc, lprc, _):
            r = lprc.contents
            rects.append((r.left, r.top, r.right, r.bottom))
            return True

        _user32.EnumDisplayMonitors(0, 0, MONITORENUMPROC(_cb), 0)
        rects.sort(key=lambda r: r[0])
        return rects

    def _move_to_monitor(number: int) -> bool:
        """Move the focused window onto monitor ``number`` (left→right)."""
        rects = _monitors()
        idx = number - 1
        if idx < 0 or idx >= len(rects):
            return False
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return False
        left, top, right, bottom = rects[idx]
        SWP_NOZORDER, SWP_SHOWWINDOW = 0x0004, 0x0040
        return bool(_user32.SetWindowPos(
            hwnd, 0, left, top, right - left, bottom - top,
            SWP_NOZORDER | SWP_SHOWWINDOW,
        ))

    _TERMINAL_INDEX = 0

    def _activate_window(hwnd) -> bool:
        if not hwnd:
            return False
        try:
            # Only un-minimize. Never restore/resize a window that is already
            # on screen: SW_RESTORE on a maximized window shrinks it off its
            # position, which reads as "it moved the window". Focus should
            # bring it forward, not relocate it.
            if _user32.IsIconic(hwnd):
                _user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            # Foreground-lock relax: a synthetic ALT release counts as user
            # input, so SetForegroundWindow is allowed from a background
            # process (voice bridge types into windows it does not own).
            try:
                import keyboard as _kb
                _kb.press_and_release("alt")
            except Exception:
                pass
            _user32.BringWindowToTop(hwnd)
            ok = bool(_user32.SetForegroundWindow(hwnd))
            try:
                _user32.SetActiveWindow(hwnd)
            except Exception:
                pass
            return ok
        except Exception:
            return False

    def _terminal_windows() -> list[dict]:
        return [
            w for w in _enumerate_app_windows()
            if w["class"].lower() in _TERMINAL_CLASSES
        ]

    def _activate_terminal_by_index(index: int) -> bool:
        global _TERMINAL_INDEX
        terminals = _terminal_windows()
        if not terminals:
            return False
        index = index % len(terminals)
        _TERMINAL_INDEX = index
        return _activate_window(terminals[index]["hwnd"])

    def _cycle_terminal(direction: int) -> bool:
        global _TERMINAL_INDEX
        terminals = _terminal_windows()
        if not terminals:
            return False
        _TERMINAL_INDEX = (_TERMINAL_INDEX + direction) % len(terminals)
        return _activate_window(terminals[_TERMINAL_INDEX]["hwnd"])

    def _move_window(direction: str) -> None:
        if direction == "left":
            _hotkey("win", "shift", "left")
        elif direction == "right":
            _hotkey("win", "shift", "right")

    def _focus_named_window(title_sub: str) -> bool:
        """Focus a visible window whose title contains ``title_sub`` (case-insensitive).

        Deterministic selection: an exact (case-insensitive) title match wins;
        otherwise the first containing match in enumeration order (topmost
        first). Zero matches -> False (caller must not type the command).
        """
        wanted = (title_sub or "").strip()
        if not wanted:
            return False
        wanted_low = wanted.lower()
        windows = _list_visible_windows()
        if not windows:
            return False
        exact = [w for w in windows if w[1].strip().lower() == wanted_low]
        cands = exact if exact else [w for w in windows if wanted_low in w[1].lower()]
        if not cands:
            return False
        return _activate_window(cands[0][0])
else:
    def _list_visible_windows() -> list:  # type: ignore[no-redef]
        return []

    def _activate_terminal_by_index(index: int) -> bool:  # type: ignore[no-redef]
        return False

    def _cycle_terminal(direction: int) -> bool:  # type: ignore[no-redef]
        return False

    def _move_window(direction: str) -> None:  # type: ignore[no-redef]
        pass

    def _focus_named_window(title_sub: str) -> bool:  # type: ignore[no-redef]
        return False

    def _focused_is_terminal() -> bool:  # type: ignore[no-redef]
        return False

    def _activate_app_window(number: int) -> bool:  # type: ignore[no-redef]
        return False

    def _activate_terminal_window(number: int) -> bool:  # type: ignore[no-redef]
        return False

    def _activate_seat(seat: str) -> bool:  # type: ignore[no-redef]
        return False

    def _move_to_monitor(number: int) -> bool:  # type: ignore[no-redef]
        return False

    def _window_map() -> list:  # type: ignore[no-redef]
        return []


# ---------------------------------------------------------------------------
# Action executor
# ---------------------------------------------------------------------------
def execute_command(action: str) -> None:
    if action in ("copy",): _hotkey("ctrl", "c")
    elif action in ("paste",): _hotkey("ctrl", "v")
    elif action in ("cut",): _hotkey("ctrl", "x")
    elif action in ("select_all",): _hotkey("ctrl", "a")
    elif action in ("undo",): _hotkey("ctrl", "z")
    elif action in ("redo",): _hotkey("ctrl", "y")
    elif action in ("save",): _hotkey("ctrl", "s")
    elif action in ("enter", "newline"): _type_text("\n")
    elif action in ("backspace",): _press("backspace")
    elif action in ("delete",):
        # In a terminal the Delete key (and Ctrl+A + Delete) do not clear a
        # dictated line. Ctrl+Up is the terminal line-delete (Kimi terminal /
        # PowerShell). Everywhere else: Delete removes the selection.
        if _focused_is_terminal():
            _hotkey("ctrl", "up")
        else:
            _press("delete")
    elif action in ("delete_up",): _hotkey("ctrl", "up")
    elif action in ("delete_word",): _hotkey("ctrl", "backspace")
    elif action in ("delete_line",):
        _hotkey("home"); _hotkey("shift", "end"); _hotkey("delete")
    elif action in ("delete_sentence",):
        _hotkey("shift", "ctrl", "left"); _hotkey("delete")
    elif action in ("clear",):
        # Terminal: wipe the current input line (Ctrl+Up). Elsewhere: select
        # all + Delete.
        if _focused_is_terminal():
            _hotkey("ctrl", "up")
        else:
            _hotkey("ctrl", "a"); _press("delete")
    elif action in ("tab",): _press("tab")
    elif action in ("space",): _press("space")
    elif action in ("period",): _type_text(".")
    elif action in ("comma",): _type_text(",")
    elif action in ("question_mark",): _type_text("?")
    elif action in ("exclamation_mark",): _type_text("!")
    elif action in ("quote",): _type_text('"')
    elif action in ("apostrophe",): _type_text("'")
    elif action in ("colon",): _type_text(":")
    elif action in ("semicolon",): _type_text(";")
    elif action in ("caps_on", "caps_off"): _press("capslock")
    elif action in ("up",): _press("up")
    elif action in ("down",): _press("down")
    elif action in ("left",): _press("left")
    elif action in ("right",): _press("right")
    elif action in ("page_up",): _press("pageup")
    elif action in ("page_down",): _press("pagedown")
    elif action in ("close_tab",): _hotkey("ctrl", "w")
    elif action in ("new_tab",): _hotkey("ctrl", "t")
    elif action in ("new_window",): _hotkey("ctrl", "n")
    elif action in ("reopen_tab",): _hotkey("ctrl", "shift", "t")
    elif action in ("close_window",): _hotkey("alt", "f4")
    elif action in ("alt_tab",): _hotkey("alt", "tab")
    elif action in ("minimize",): _hotkey("win", "down")
    elif action in ("maximize",): _hotkey("win", "up")
    elif action in ("show_desktop",): _hotkey("win", "d")
    elif action in ("task_view",): _hotkey("win", "tab")
    elif action in ("back",): _hotkey("alt", "left")
    elif action in ("forward",): _hotkey("alt", "right")
    elif action in ("refresh",): _press("f5")
    elif action in ("find",): _hotkey("ctrl", "f")
    elif action in ("zoom_in",): _hotkey("ctrl", "+")
    elif action in ("zoom_out",): _hotkey("ctrl", "-")
    elif action in ("cancel",): _press("escape")
    elif action in ("switch_window",): _cycle_terminal(1)
    elif action in ("previous_window",): _cycle_terminal(-1)
    elif action in ("window_a",): _activate_terminal_by_index(0)
    elif action in ("window_b",): _activate_terminal_by_index(1)
    elif action in ("window_c",): _activate_terminal_by_index(2)
    elif action in ("window_d",): _activate_terminal_by_index(3)
    elif action.startswith("screen_"):
        _n = action.split("_", 1)[1]
        _move_to_monitor(int(_n) if _n.isdigit() else 0)
    elif action.startswith("window_") and action[7:].isdigit():
        _activate_app_window(int(action[7:]))
    elif action.startswith("terminal_") and action[9:].isdigit():
        _activate_terminal_window(int(action[9:]))
    elif action.startswith("devpad_") and action[7:].isdigit():
        _focus_devpad_tile(int(action[7:]))
    elif action in ("list_windows",):
        lines = _window_map()
        text = " | ".join(lines) if lines else "no windows found"
        print("WINDOWS: " + text)
        return text
    elif action in ("screenshot",):
        _screenshot()
    elif action in ("start_cockpit",):
        _start_cockpit()
    elif action in ("start_handoff",):
        _start_handoff()
    elif action in _FOCUS_LABELS:
        return _focus_named_window(_FOCUS_LABELS[action])
    elif action in ("reconnect",):
        _trigger_reconnect()
    elif action in ("macro_proofread",):
        _macro("proofread")
    elif action in ("macro_concise",):
        _macro("concise")
    elif action in ("macro_format",):
        _macro("format")
    elif action in ("command_mode",):
        pass