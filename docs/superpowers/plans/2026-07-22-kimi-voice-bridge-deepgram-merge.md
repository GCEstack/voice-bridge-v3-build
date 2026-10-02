# Kimi Voice Bridge + Deepgram Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `kimi-voice-bridge`'s local Whisper STT with the Deepgram streaming pipeline from `C:\Lares_Family\Tools\voice`, while preserving the tray UI, global push-to-talk hotkey, and "Speak replies" TTS.

**Architecture:** Copy `capture.py`, `speech_corrector.py`, and the voice-profile data into `kimi-voice-bridge/src/`. Extract a focused command parser from `voice_access.py` into `src/voice_commands.py`. Refactor `src/voice_bridge.py` to start/stop `DeepgramCapture` on hotkey press/release, apply `speech_corrector` to final transcripts, then either execute a voice command or type the corrected text into the focused window.

**Tech Stack:** Python 3.11+, `keyboard`, `sounddevice`, `websockets`, `pyautogui`, `pyttsx3`, `pyperclip`, `PyYAML`, `python-dotenv`.

## Global Constraints

- Python 3.11 or higher.
- All dependencies pinned in `requirements.txt`.
- Runs on Windows first; macOS is not required for this merge.
- No local Whisper model; STT runs through Deepgram API.
- Voice profile path defaults to `~/.kimi-code/voice-profile.json`, then local `src/voice-profile.json`.
- Deepgram API key loaded from `config.json`, then `DEEPGRAM_API_KEY` env var, then `.env`.
- Push-to-talk only; no always-on mode.
- User must focus the target window before releasing the hotkey.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `requirements.txt` | Modify | Add `websockets`, `python-dotenv`, `pyautogui`, `PyYAML`; remove `faster-whisper` and `SpeechRecognition`. |
| `config.json` | Modify | Add `deepgram_api_key` and `voice_profile_path`; remove `stt_model` and `language`. |
| `src/config.py` | Modify | Update `DEFAULT_CONFIG` to match `config.json`. |
| `src/capture.py` | Create (copy from Deepgram project) | Deepgram WebSocket streaming capture. |
| `src/speech_corrector.py` | Create (copy from Deepgram project) | Profile-based transcript corrections. |
| `src/voice-profile.json` | Create (copy from Deepgram project) | Local fallback voice profile. |
| `src/markers.json` | Create (copy from Deepgram project) | Tone markers for `speech_corrector`. |
| `src/corrections.json` | Create (copy from Deepgram project) | Seeded word/phrase corrections. |
| `src/voice_commands.py` | Create | Command parser and executor extracted from `voice_access.py`. |
| `src/voice_bridge.py` | Modify | Tray UI + hotkey orchestration using `DeepgramCapture`. |
| `src/clipboard_watcher.py` | Keep | Clipboard monitoring for spoken replies. |
| `src/keyboard_input.py` | Keep | Text injection helpers. |
| `src/tts.py` | Keep | Text-to-speech for replies. |
| `src/audio.py` | Delete | No longer needed. |
| `src/stt.py` | Delete | No longer needed. |
| `tests/test_voice_bridge.py` | Modify | Mock `DeepgramCapture` and `voice_commands`. |
| `tests/test_integration.py` | Modify | Mock `DeepgramCapture` and `voice_commands`. |
| `tests/test_voice_commands.py` | Create | Test core command parsing/execution. |
| `tests/test_stt.py` | Delete | Obsolete. |
| `tests/test_audio.py` | Delete | Obsolete. |

---

### Task 1: Update Dependencies

**Files:**
- Modify: `requirements.txt`

**Interfaces:**
- Produces: dependency list with Deepgram pipeline packages.

- [ ] **Step 1: Replace the contents of `requirements.txt`**

```text
keyboard==0.13.5
sounddevice==0.4.7
websockets==13.1
python-dotenv==1.0.1
pyautogui==0.9.54
pyttsx3==2.98
pyperclip==1.9.0
pytest==8.3.5
numpy==2.2.4
requests==2.32.3
PyYAML==6.0.2
```

- [ ] **Step 2: Install dependencies**

Run: `python -m pip install -r requirements.txt`

Expected: installs without errors; `websockets`, `python-dotenv`, `pyautogui`, `PyYAML` are present.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "deps: switch to Deepgram pipeline packages"
```

---

### Task 2: Copy Deepgram Pipeline Files

**Files:**
- Create: `src/capture.py`
- Create: `src/speech_corrector.py`
- Create: `src/voice-profile.json`
- Create: `src/markers.json`
- Create: `src/corrections.json`

**Interfaces:**
- Produces: `DeepgramCapture`, `CaptureConfig`, `DeepgramAuthError` in `src/capture.py`.
- Produces: `apply_corrections`, `correct_text_fast`, `load` in `src/speech_corrector.py`.

- [ ] **Step 1: Copy files from the Deepgram project**

Source files are in `C:\Lares_Family\Tools\voice\`:
- `capture.py` → `src/capture.py`
- `speech_corrector.py` → `src/speech_corrector.py`
- `voice-profile.json` → `src/voice-profile.json`
- `markers.json` → `src/markers.json`
- `corrections.json` → `src/corrections.json`

- [ ] **Step 2: Patch `src/speech_corrector.py` to honor `VOICE_PROFILE_PATH`**

Modify `_load_voice_profile()` to check the environment variable first:

```python
def _load_voice_profile() -> dict:
    """Load the Dekan voice profile from explicit path, user-global Kimi Code location, or local fallback."""
    explicit = os.getenv("VOICE_PROFILE_PATH")
    if explicit:
        path = Path(explicit)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    home_profile = Path.home() / ".kimi-code" / "voice-profile.json"
    if home_profile.exists():
        with open(home_profile, "r", encoding="utf-8") as f:
            return json.load(f)
    return _load_json("voice-profile.json")
```

- [ ] **Step 3: Verify imports work**

- [ ] **Step 2: Verify imports work**

Run:
```bash
python -c "from src.capture import DeepgramCapture, CaptureConfig, DeepgramAuthError; from src.speech_corrector import apply_corrections, load; print('OK')"
```

Expected: prints `OK`.

- [ ] **Step 3: Commit**

```bash
git add src/capture.py src/speech_corrector.py src/voice-profile.json src/markers.json src/corrections.json
git commit -m "feat: import Deepgram capture and speech corrector"
```

---

### Task 3: Update Configuration

**Files:**
- Modify: `src/config.py`
- Modify: `config.json`

**Interfaces:**
- Produces: `DEFAULT_CONFIG` with `deepgram_api_key` and `voice_profile_path`.

- [ ] **Step 1: Modify `src/config.py`**

Replace `DEFAULT_CONFIG` with:

```python
DEFAULT_CONFIG = {
    "dictation_hotkey": "ctrl+shift+space",
    "speak_replies": False,
    "clipboard_window_seconds": 30,
    "mic_device": "default",
    "tts_voice": "default",
    "deepgram_api_key": "",
    "voice_profile_path": "",
    "sample_rate": 16000,
    "channels": 1,
}
```

- [ ] **Step 2: Modify `config.json`**

Replace the file contents with:

```json
{
  "dictation_hotkey": "ctrl+shift+space",
  "speak_replies": false,
  "clipboard_window_seconds": 30,
  "mic_device": "default",
  "tts_voice": "default",
  "deepgram_api_key": "",
  "voice_profile_path": "",
  "sample_rate": 16000,
  "channels": 1
}
```

- [ ] **Step 3: Run config tests**

Run: `python -m pytest tests/test_config.py -v`

Expected: tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/config.py config.json
git commit -m "config: switch to Deepgram settings"
```

---

### Task 4: Create Voice Commands Module

**Files:**
- Create: `src/voice_commands.py`
- Create: `tests/test_voice_commands.py`

**Interfaces:**
- Produces: `handle_command(text: str) -> str | None` — returns `None` if not a command, otherwise a description like `"enter"`, `"copy"`, etc.
- Produces: `execute_command(action: str) -> None` — performs the keyboard action.

- [ ] **Step 1: Write the failing test**

Create `tests/test_voice_commands.py`:

```python
from unittest.mock import patch

from src.voice_commands import handle_command, execute_command


def test_handle_command_recognizes_copy():
    assert handle_command("copy that") == "copy"


def test_handle_command_returns_none_for_plain_text():
    assert handle_command("hello world") is None


@patch("src.voice_commands.pyautogui.hotkey")
def test_execute_command_copy(mock_hotkey):
    execute_command("copy")
    mock_hotkey.assert_called_once_with("ctrl", "c")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_voice_commands.py -v`

Expected: `ModuleNotFoundError: No module named 'src.voice_commands'`.

- [ ] **Step 3: Create minimal `src/voice_commands.py`**

```python
"""Voice command parser and executor extracted from voice_access.py."""

try:
    import pyautogui
except ImportError:
    pyautogui = None  # type: ignore[assignment]


_COMMANDS = {
    # Session
    "sleep": "sleep",
    "voice sleep": "sleep",
    "wake": "wake",
    "wake up": "wake",
    "voice wake up": "wake",
    "continue": "wake",
    "go ahead": "wake",
    "quit": "quit",
    "exit": "quit",

    # Text editing
    "new line": "newline",
    "next line": "newline",
    "delete that": "backspace",
    "delete word": "delete_word",
    "remove word": "delete_word",
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
    "tab": "tab",
    "space": "space",
    "period": "period",
    "comma": "comma",
    "question mark": "question_mark",
    "exclamation mark": "exclamation_mark",
    "quote": "quote",
    "apostrophe": "apostrophe",
    "colon": "colon",
    "semicolon": "semicolon",

    # Messaging
    "send": "enter",
    "send message": "enter",
    "send it": "enter",
    "enter": "enter",
    "return": "enter",
    "new paragraph": "enter",

    # Caps lock
    "caps on": "caps_on",
    "caps lock on": "caps_on",
    "caps off": "caps_off",
    "caps lock off": "caps_off",

    # Navigation
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "page up": "page_up",
    "page down": "page_down",

    # Window / tab
    "close tab": "close_tab",
    "new tab": "new_tab",
}


def handle_command(text: str) -> str | None:
    """Return action string if text starts with a known command phrase."""
    words = text.lower().strip().rstrip(".,;:!?").split()
    if not words:
        return None
    for phrase in sorted(_COMMANDS, key=len, reverse=True):
        phrase_words = phrase.split()
        if len(words) >= len(phrase_words) and words[:len(phrase_words)] == phrase_words:
            return _COMMANDS[phrase]
    return None


def _type_text(text: str) -> None:
    if pyautogui is not None:
        pyautogui.typewrite(text, interval=0.01)


def execute_command(action: str) -> None:
    """Execute a keyboard action."""
    if pyautogui is None:
        return

    if action == "copy":
        pyautogui.hotkey("ctrl", "c")
    elif action == "paste":
        pyautogui.hotkey("ctrl", "v")
    elif action == "cut":
        pyautogui.hotkey("ctrl", "x")
    elif action == "select_all":
        pyautogui.hotkey("ctrl", "a")
    elif action == "undo":
        pyautogui.hotkey("ctrl", "z")
    elif action == "redo":
        pyautogui.hotkey("ctrl", "y")
    elif action == "save":
        pyautogui.hotkey("ctrl", "s")
    elif action == "enter" or action == "newline":
        _type_text("\n")
    elif action == "backspace":
        _type_text("\b")
    elif action == "delete_word":
        pyautogui.hotkey("ctrl", "backspace")
    elif action == "clear":
        _type_text("\n" * 3)
    elif action == "tab":
        pyautogui.press("tab")
    elif action == "space":
        pyautogui.press("space")
    elif action == "period":
        _type_text(".")
    elif action == "comma":
        _type_text(",")
    elif action == "question_mark":
        _type_text("?")
    elif action == "exclamation_mark":
        _type_text("!")
    elif action == "quote":
        _type_text('"')
    elif action == "apostrophe":
        _type_text("'")
    elif action == "colon":
        _type_text(":")
    elif action == "semicolon":
        _type_text(";")
    elif action == "caps_on":
        pyautogui.press("capslock")
    elif action == "caps_off":
        pyautogui.press("capslock")
    elif action == "up":
        pyautogui.press("up")
    elif action == "down":
        pyautogui.press("down")
    elif action == "left":
        pyautogui.press("left")
    elif action == "right":
        pyautogui.press("right")
    elif action == "page_up":
        pyautogui.press("pageup")
    elif action == "page_down":
        pyautogui.press("pagedown")
    elif action == "close_tab":
        pyautogui.hotkey("ctrl", "w")
    elif action == "new_tab":
        pyautogui.hotkey("ctrl", "t")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_voice_commands.py -v`

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/voice_commands.py tests/test_voice_commands.py
git commit -m "feat: add voice command parser and executor"
```

---

### Task 5: Refactor `src/voice_bridge.py` for Deepgram

**Files:**
- Modify: `src/voice_bridge.py`

**Interfaces:**
- Consumes: `DeepgramCapture`, `CaptureConfig` from `src.capture`.
- Consumes: `apply_corrections`, `load` from `src.speech_corrector`.
- Consumes: `handle_command`, `execute_command` from `src.voice_commands`.
- Produces: `VoiceBridge` class with the same public API (`run()`).

- [ ] **Step 1: Write the failing test**

Modify `tests/test_voice_bridge.py`:

```python
from unittest.mock import MagicMock, patch

from src.voice_bridge import VoiceBridge


@patch("src.voice_bridge.load_config")
@patch("src.voice_bridge.DeepgramCapture")
@patch("src.voice_bridge.TTS")
@patch("src.voice_bridge.ClipboardWatcher")
@patch("src.voice_bridge.type_text")
@patch("src.voice_bridge.press_enter")
@patch("src.voice_bridge.keyboard")
def test_voice_bridge_types_corrected_transcript(
    mock_keyboard,
    mock_press_enter,
    mock_type_text,
    mock_watcher_cls,
    mock_tts_cls,
    mock_capture_cls,
    mock_load_config,
):
    mock_load_config.return_value = {
        "dictation_hotkey": "ctrl+shift+space",
        "speak_replies": False,
        "clipboard_window_seconds": 30,
        "mic_device": "default",
        "tts_voice": "default",
        "deepgram_api_key": "test-key",
        "voice_profile_path": "",
        "sample_rate": 16000,
        "channels": 1,
    }

    mock_capture = MagicMock()
    mock_capture_cls.return_value = mock_capture

    bridge = VoiceBridge()
    bridge._transcripts = ["hello world"]
    bridge._finish_dictation()

    mock_capture.stop.assert_called_once()
    mock_type_text.assert_called_once_with("Hello world ", interval=0.01)
    mock_press_enter.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_voice_bridge.py -v`

Expected: fails because `src.voice_bridge` still imports `AudioRecorder` and `STT`.

- [ ] **Step 3: Rewrite `src/voice_bridge.py`**

Replace the file contents with:

```python
import os
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import keyboard

from src.capture import CaptureConfig, DeepgramAuthError, DeepgramCapture
from src.clipboard_watcher import ClipboardWatcher
from src.config import load_config
from src.keyboard_input import press_enter, type_text
from src.speech_corrector import apply_corrections, load as load_corrector
from src.tts import TTS
from src.voice_commands import execute_command, handle_command


class VoiceBridge:
    def __init__(self, config_path: str = "config.json"):
        self.config = load_config(config_path)
        self.tts = TTS(voice_id=self.config["tts_voice"])
        self.speak_replies_value = self.config["speak_replies"]
        self.speak_replies = None
        self.hotkey = self.config["dictation_hotkey"]
        self.recording = False
        self.root = None
        self.status_label = None

        # Deepgram API key: config > env > .env
        self.deepgram_api_key = self.config.get("deepgram_api_key") or os.getenv("DEEPGRAM_API_KEY")
        if not self.deepgram_api_key and Path(".env").exists():
            try:
                from dotenv import load_dotenv
                load_dotenv(".env", override=True)
                self.deepgram_api_key = os.getenv("DEEPGRAM_API_KEY")
            except Exception:
                pass

        # Load corrector (voice profile path defaults handled internally).
        profile_path = self.config.get("voice_profile_path") or None
        if profile_path:
            os.environ["VOICE_PROFILE_PATH"] = str(profile_path)
        load_corrector()

        self.capture: DeepgramCapture | None = None
        self._transcripts: list[str] = []

    def run(self):
        self.root = tk.Tk()
        self.root.title("Kimi Voice Bridge")
        self.root.geometry("300x150")
        self.root.attributes("-topmost", True)
        self.speak_replies = tk.BooleanVar(value=self.speak_replies_value)

        ttk.Label(self.root, text="Kimi Voice Bridge", font=("Arial", 14)).pack(pady=10)

        self.status_label = ttk.Label(self.root, text="Ready")
        self.status_label.pack(pady=5)

        ttk.Checkbutton(
            self.root,
            text="Speak replies",
            variable=self.speak_replies,
            command=self._on_toggle_change,
        ).pack(pady=5)

        ttk.Label(
            self.root,
            text=f"Hold {self.hotkey} to speak",
            font=("Arial", 9),
        ).pack(pady=5)

        self._setup_hotkey()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _setup_hotkey(self):
        keyboard.add_hotkey(self.hotkey, self._on_hotkey_press, trigger_on_release=False)
        keyboard.add_hotkey(self.hotkey, self._on_hotkey_release, trigger_on_release=True)

    def _on_hotkey_press(self):
        if self.recording:
            return
        if not self.deepgram_api_key:
            self._set_status("Error: no Deepgram API key")
            return

        self.recording = True
        self._transcripts = []
        self._set_status("Listening...")

        cfg = CaptureConfig(
            api_key=self.deepgram_api_key,
            device_index=self.config.get("mic_device") if self.config.get("mic_device") != "default" else None,
            mode="push_to_talk",
            endpointing_ms=300,
            utterance_end_ms=1000,
        )
        self.capture = DeepgramCapture(cfg)
        self.capture.on_transcript = self._on_transcript
        try:
            self.capture.start()
        except Exception as e:
            self._set_status(f"Mic error: {e}")
            self.recording = False

    def _on_transcript(self, text: str, is_final: bool):
        if not is_final:
            return
        self._transcripts.append(text)
        self._set_status(f"Heard: {text[:40]}")

    def _on_hotkey_release(self):
        if not self.recording or self.capture is None:
            return
        self._set_status("Processing...")
        thread = threading.Thread(target=self._finish_dictation, daemon=True)
        thread.start()

    def _speak_replies_enabled(self) -> bool:
        if self.speak_replies is None:
            return self.speak_replies_value
        return self.speak_replies.get()

    def _finish_dictation(self):
        if self.capture is None:
            return
        self.capture.stop()
        # Wait briefly for the final transcript to arrive.
        self.capture._thread.join(timeout=2.0) if self.capture._thread else None
        self.recording = False

        raw = " ".join(self._transcripts).strip()
        if not raw:
            self._set_status("No speech detected")
            return

        try:
            corrected = apply_corrections(raw)
        except Exception as e:
            self._set_status(f"Correction error: {e}")
            corrected = raw

        action = handle_command(corrected)
        if action is not None:
            if action == "quit":
                self._on_close()
                return
            try:
                execute_command(action)
                self._set_status(f"Command: {action}")
            except Exception as e:
                self._set_status(f"Command error: {e}")
            return

        try:
            type_text(corrected + " ", interval=0.01)
            press_enter()
            self._set_status(f"Sent: {corrected[:40]}")
            if self._speak_replies_enabled():
                self._speak_reply()
        except Exception as e:
            self._set_status(f"Dictation failed: {e}")

    def _speak_reply(self):
        watcher = ClipboardWatcher(
            window_seconds=self.config["clipboard_window_seconds"]
        )
        watcher.start()
        deadline = time.time() + self.config["clipboard_window_seconds"]
        while time.time() < deadline:
            text = watcher.get_new_text()
            if text:
                watcher.stop()
                self._set_status("Speaking reply...")
                self.tts.speak(text)
                self._set_status("Ready")
                return
            time.sleep(0.2)
        watcher.stop()
        self._set_status("Ready")

    def _on_toggle_change(self):
        state = "ON" if self._speak_replies_enabled() else "OFF"
        self._set_status(f"Speak replies: {state}")

    def _set_status(self, message: str):
        if self.status_label and self.root:
            self.root.after(0, lambda: self.status_label.config(text=message))
        print(message)

    def _on_close(self):
        keyboard.unhook_all_hotkeys()
        if self.capture is not None:
            self.capture.stop()
        if self.root is not None:
            self.root.destroy()


if __name__ == "__main__":
    bridge = VoiceBridge()
    bridge.run()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_voice_bridge.py -v`

Expected: test passes.

- [ ] **Step 5: Commit**

```bash
git add src/voice_bridge.py tests/test_voice_bridge.py
git commit -m "feat: wire Deepgram capture and voice commands into bridge"
```

---

### Task 6: Remove Obsolete Files

**Files:**
- Delete: `src/audio.py`
- Delete: `src/stt.py`
- Delete: `tests/test_audio.py`
- Delete: `tests/test_stt.py`

- [ ] **Step 1: Delete files**

```bash
git rm src/audio.py src/stt.py tests/test_audio.py tests/test_stt.py
```

- [ ] **Step 2: Run remaining tests**

Run: `python -m pytest tests/ -v`

Expected: all remaining tests pass.

- [ ] **Step 3: Commit**

```bash
git commit -m "chore: remove obsolete Whisper audio/stt modules"
```

---

### Task 7: Update Integration Test

**Files:**
- Modify: `tests/test_integration.py`

**Interfaces:**
- Consumes: mocked `DeepgramCapture`, `TTS`, `ClipboardWatcher`, `type_text`, `press_enter`.

- [ ] **Step 1: Modify `tests/test_integration.py`**

Replace the file contents with:

```python
from unittest.mock import MagicMock, patch

from src.voice_bridge import VoiceBridge


@patch("src.voice_bridge.load_config")
@patch("src.voice_bridge.DeepgramCapture")
@patch("src.voice_bridge.TTS")
@patch("src.voice_bridge.ClipboardWatcher")
@patch("src.voice_bridge.type_text")
@patch("src.voice_bridge.press_enter")
@patch("src.voice_bridge.keyboard")
def test_full_flow_with_tts_toggle(
    mock_keyboard,
    mock_press_enter,
    mock_type_text,
    mock_watcher_cls,
    mock_tts_cls,
    mock_capture_cls,
    mock_load_config,
):
    mock_load_config.return_value = {
        "dictation_hotkey": "ctrl+shift+space",
        "speak_replies": True,
        "clipboard_window_seconds": 1,
        "mic_device": "default",
        "tts_voice": "default",
        "deepgram_api_key": "test-key",
        "voice_profile_path": "",
        "sample_rate": 16000,
        "channels": 1,
    }

    mock_capture = MagicMock()
    mock_capture_cls.return_value = mock_capture
    mock_tts = MagicMock()
    mock_tts_cls.return_value = mock_tts
    mock_watcher = MagicMock()
    mock_watcher.get_new_text.return_value = "Hi there"
    mock_watcher_cls.return_value = mock_watcher

    bridge = VoiceBridge()
    bridge._transcripts = ["hello kim"]
    bridge._finish_dictation()

    mock_type_text.assert_called_once_with("Hello kim ", interval=0.01)
    mock_tts.speak.assert_called_once_with("Hi there")
```

- [ ] **Step 2: Run integration test**

Run: `python -m pytest tests/test_integration.py -v`

Expected: test passes.

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: update integration test for Deepgram pipeline"
```

---

### Task 8: Manual Verification

**Files:**
- Create: `.env` (or use existing)

- [ ] **Step 1: Add Deepgram API key**

Create `.env` in `kimi-voice-bridge/`:

```text
DEEPGRAM_API_KEY=your-key-here
```

- [ ] **Step 2: Run the app**

Run: `python src/voice_bridge.py`

Expected: window appears with "Ready" status.

- [ ] **Step 3: Test dictation**

1. Click into a text editor or browser field.
2. Hold `Ctrl+Shift+Space`.
3. Speak "hello world".
4. Release the hotkey.

Expected: corrected text "Hello world " appears in the focused window, followed by Enter.

- [ ] **Step 4: Test a voice command**

1. Hold `Ctrl+Shift+Space`.
2. Speak "copy that" (with some text selected).
3. Release.

Expected: selected text is copied to clipboard.

- [ ] **Step 5: Test spoken replies**

1. Check "Speak replies" in the window.
2. Dictate a message and send it.
3. Within 30 seconds, copy a reply to the clipboard.

Expected: TTS reads the reply aloud.

- [ ] **Step 6: Commit `.env.example`**

If not present, create `.env.example`:

```text
DEEPGRAM_API_KEY=your-key-here
```

Do NOT commit the real `.env`.

```bash
git add .env.example
git commit -m "docs: add .env.example for Deepgram key"
```

---

## Self-Review

- **Spec coverage:**
  - Deepgram STT replacement → Tasks 2, 5
  - Voice profile corrections → Tasks 2, 5
  - Voice commands → Tasks 4, 5
  - Tray UI/hotkey preservation → Task 5
  - Speak replies TTS → Task 5
  - Any-window typing → Task 5 (uses existing `keyboard_input`)
  - Push-to-talk only → Task 5
  - Config updates → Tasks 1, 3
  - Tests → Tasks 4, 5, 6, 7
  - Manual verification → Task 8

- **Placeholder scan:** No TBD/TODO; every step has exact code/commands.
- **Type consistency:** `DeepgramCapture`, `CaptureConfig`, `apply_corrections`, `handle_command`, `execute_command` used consistently.
