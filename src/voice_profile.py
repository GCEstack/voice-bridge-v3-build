"""Voice profile loader.

Loads `voice-profile.json` (parent-child structure) mapping spoken phrases to
tool-specific terminal commands (opencode, claude, kimi, ...).

Parents = AI tools; children = {voice phrase: command}. A command is either:

- a string slash-command (e.g. "/sessions") -> typed verbatim, or
- a keybind object {"key": "...", "keys": ["ctrl","x","f"]} -> fired as a
  hotkey (used for opencode session_fork, which has no slash command).

When the user speaks a phrase, the matched command is dispatched into the
focused terminal.
"""

import json
import os

_PROFILE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "voice-profile.json"
)

_PROFILE: dict = {}
_SLASH: dict[str, str] = {}      # phrase(lower) -> slash command string
_HOTKEY: dict[str, dict] = {}    # phrase(lower) -> {"key":..., "keys":[...]}


def load_profile(path: str | None = None) -> dict:
    global _PROFILE, _SLASH, _HOTKEY
    p = path or _PROFILE_PATH
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                _PROFILE = json.load(f)
        except Exception:
            _PROFILE = {}
    _SLASH = {}
    _HOTKEY = {}
    for tool, node in _PROFILE.items():
        commands = node.get("commands", {}) if isinstance(node, dict) else {}
        for phrase, cmd in commands.items():
            phrase = phrase.strip().lower()
            if isinstance(cmd, dict) and "keys" in cmd:
                _HOTKEY[phrase] = cmd
            else:
                _SLASH[phrase] = cmd
    return _PROFILE


def _resolve(text: str) -> str:
    return text.strip().lower().rstrip(".,;:!?")


def profile_command(text: str) -> str | None:
    """Return the slash command for a spoken phrase, or None if no match."""
    if not _SLASH and not _HOTKEY:
        load_profile()
    return _SLASH.get(_resolve(text))


def profile_hotkey(text: str) -> dict | None:
    """Return the keybind object for a spoken phrase, or None if no match."""
    if not _SLASH and not _HOTKEY:
        load_profile()
    return _HOTKEY.get(_resolve(text))