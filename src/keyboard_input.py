"""Keyboard injection helpers.

`type_text` types into the foreground (focused) window via the `keyboard`
library. To keep dictation landing in the user's terminal (not the bridge's own
topmost control window), we remember the foreground window at ARM time and
re-activate it right before injecting keys.
"""

import ctypes
from ctypes import wintypes

import keyboard

_user32 = ctypes.windll.user32
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.IsWindow.argtypes = [wintypes.HWND]
_user32.IsWindow.restype = wintypes.BOOL
_user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_user32.GetWindowTextLengthW.restype = ctypes.c_int
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetWindowTextW.restype = ctypes.c_int
_user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetClassNameW.restype = ctypes.c_int

_TARGET_HWND = None


def lock_target_window():
    """Remember the currently focused window so typing returns to it later."""
    global _TARGET_HWND
    hwnd = _user32.GetForegroundWindow()
    if hwnd:
        _TARGET_HWND = hwnd


def _restore_target():
    global _TARGET_HWND
    if not _TARGET_HWND:
        return
    if _user32.IsWindow(_TARGET_HWND):
        try:
            _user32.SetForegroundWindow(_TARGET_HWND)
        except Exception:
            pass


def restore_target_window() -> None:
    """Re-activate the remembered target window before injecting keys.

    Dictation already does this via ``type_text``; command hotkeys (Ctrl+C/V,
    undo, etc.) must do it too or they can land in the wrong window — e.g. the
    always-on-top VoiceBridge control window.
    """
    _restore_target()


def type_text(text: str, interval: float = 0.01):
    if not text:
        return
    _restore_target()
    keyboard.write(text, delay=interval)


def press_enter():
    _restore_target()
    keyboard.press_and_release("return")


def target_window_title() -> str:
    """Title of the remembered target window ('' if unknown/closed).

    Used by voice_commands to make commands context-aware (e.g. a terminal
    needs Esc to wipe the input line, not Ctrl+A + Delete).
    """
    if not _TARGET_HWND or not _user32.IsWindow(_TARGET_HWND):
        return ""
    length = _user32.GetWindowTextLengthW(_TARGET_HWND)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(_TARGET_HWND, buf, length + 1)
    return buf.value


def target_window_class() -> str:
    """Window class name of the remembered target window ('' if unknown).

    More reliable than the title for "is this a terminal?" — a console is
    ``ConsoleWindowClass`` (conhost) or ``CASCADIA_HOSTING_WINDOW_CLASS``
    (Windows Terminal) no matter what is running inside it.
    """
    if not _TARGET_HWND or not _user32.IsWindow(_TARGET_HWND):
        return ""
    buf = ctypes.create_unicode_buffer(256)
    n = _user32.GetClassNameW(_TARGET_HWND, buf, 256)
    return buf.value if n else ""