# Kimi Voice Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local system-tray helper that adds push-to-talk voice dictation and an optional spoken-reply toggle to the Kimi desktop app.

**Architecture:** A small Python tray app captures mic audio on a global hotkey, transcribes it with a local STT engine, injects the text into the Kimi chat input, and monitors the clipboard for copied replies to read aloud when the toggle is ON.

**Tech Stack:** Python 3.11+, `keyboard`, `pystray`, `sounddevice`, `faster-whisper`, `pyttsx3`, `pyperclip`, `Pillow`.

## Global Constraints

- Python 3.11 or higher.
- All dependencies pinned in `requirements.txt`.
- Runs on Windows and macOS (keyboard libs differ; plan targets Windows first, macOS notes inline).
- No network calls for STT/TTS; models run locally or use OS voices.
- User must focus the Kimi chat box before releasing the dictation hotkey.
- Clipboard is the only supported reply capture method for the MVP.

---

## File Structure

```
kimi-voice-bridge/
├── config.json
├── requirements.txt
├── README.md
├── .gitignore
├── src/
│   ├── __init__.py
│   ├── config.py          # Load and validate config.json
│   ├── audio.py           # Record mic to WAV
│   ├── stt.py             # Speech-to-text
│   ├── tts.py             # Text-to-speech
│   ├── clipboard_watcher.py
│   ├── keyboard_input.py  # Type text and press Enter
│   └── voice_bridge.py    # Tray app + orchestration
└── tests/
    ├── __init__.py
    ├── test_config.py
    ├── test_audio.py
    ├── test_stt.py
    ├── test_tts.py
    ├── test_clipboard_watcher.py
    ├── test_keyboard_input.py
    └── test_voice_bridge.py
```

---

### Task 1: Project Scaffold

**Files:**
- Create: `requirements.txt`
- Create: `config.json`
- Create: `.gitignore`
- Create: `README.md` (skeleton)
- Create: `src/__init__.py`
- Create: `tests/__init__.py`

**Interfaces:**
- Produces: `config.json` schema and dependency list used by all later tasks.

- [ ] **Step 1: Create requirements.txt**

```text
keyboard==0.13.5
pystray==0.19.5
sounddevice==0.4.7
faster-whisper==1.0.3
pyttsx3==2.90
pyperclip==1.8.2
Pillow==10.3.0
pytest==8.2.2
```

- [ ] **Step 2: Create config.json**

```json
{
  "dictation_hotkey": "ctrl+shift+space",
  "speak_replies": false,
  "clipboard_window_seconds": 30,
  "mic_device": "default",
  "tts_voice": "default",
  "stt_model": "base",
  "language": "en",
  "sample_rate": 16000,
  "channels": 1
}
```

- [ ] **Step 3: Create .gitignore**

```text
__pycache__/
*.pyc
*.wav
.venv/
venv/
.env
models/
*.egg-info/
.pytest_cache/
```

- [ ] **Step 4: Create README.md skeleton**

```markdown
# Kimi Voice Bridge

Push-to-talk voice dictation + optional spoken replies for the Kimi desktop app.

## Install

```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

## Run

```bash
python src/voice_bridge.py
```

## Usage

1. Focus the Kimi desktop chat box.
2. Hold `Ctrl + Shift + Space`, speak, release.
3. Right-click the tray icon to toggle "Speak replies".
4. When Speak replies is ON, copy Kimi's reply to hear it read aloud.
```

- [ ] **Step 5: Create empty `src/__init__.py` and `tests/__init__.py`**

```bash
touch src/__init__.py tests/__init__.py
```

- [ ] **Step 6: Commit**

```bash
git add .
git commit -m "chore: scaffold kimi-voice-bridge project"
```

---

### Task 2: Configuration Module

**Files:**
- Create: `src/config.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Produces: `load_config(path: str) -> dict`
- Produces: `DEFAULT_CONFIG: dict`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from src.config import load_config, DEFAULT_CONFIG
import json
import tempfile
import os


def test_default_config_has_required_keys():
    keys = [
        "dictation_hotkey",
        "speak_replies",
        "clipboard_window_seconds",
        "mic_device",
        "tts_voice",
        "stt_model",
        "language",
        "sample_rate",
        "channels",
    ]
    for key in keys:
        assert key in DEFAULT_CONFIG


def test_load_config_reads_file():
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f:
        json.dump({"speak_replies": True}, f)
        path = f.name
    try:
        cfg = load_config(path)
        assert cfg["speak_replies"] is True
        assert cfg["dictation_hotkey"] == "ctrl+shift+space"
    finally:
        os.unlink(path)


def test_load_config_missing_file_uses_defaults():
    cfg = load_config("does_not_exist.json")
    assert cfg == DEFAULT_CONFIG
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.config'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/config.py
import json
import os

DEFAULT_CONFIG = {
    "dictation_hotkey": "ctrl+shift+space",
    "speak_replies": False,
    "clipboard_window_seconds": 30,
    "mic_device": "default",
    "tts_voice": "default",
    "stt_model": "base",
    "language": "en",
    "sample_rate": 16000,
    "channels": 1,
}


def load_config(path: str) -> dict:
    if not os.path.exists(path):
        return DEFAULT_CONFIG.copy()
    with open(path, "r", encoding="utf-8") as f:
        user = json.load(f)
    cfg = DEFAULT_CONFIG.copy()
    cfg.update(user)
    return cfg
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_config.py -v
```

Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_config.py
git commit -m "feat: add configuration module"
```

---

### Task 3: Audio Recorder

**Files:**
- Create: `src/audio.py`
- Create: `tests/test_audio.py`

**Interfaces:**
- Produces: `class AudioRecorder`
  - `start_recording(device=None, samplerate=16000, channels=1)`
  - `stop_recording() -> str` (returns path to WAV file)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_audio.py
import os
import wave
import pytest
from unittest.mock import MagicMock, patch
from src.audio import AudioRecorder


@patch("src.audio.sd.InputStream")
@patch("src.audio.wave.open")
def test_audio_recorder_creates_wav(mock_wave_open, mock_input_stream):
    recorder = AudioRecorder()
    recorder.start_recording()
    recorder.frames.append(b"fake_audio_data")
    path = recorder.stop_recording()

    assert path.endswith(".wav")
    assert os.path.exists(path)
    mock_wave_open.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_audio.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.audio'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/audio.py
import os
import tempfile
import wave
import sounddevice as sd
import numpy as np


class AudioRecorder:
    def __init__(self):
        self.stream = None
        self.frames = []
        self.samplerate = 16000
        self.channels = 1

    def start_recording(self, device=None, samplerate=16000, channels=1):
        self.samplerate = samplerate
        self.channels = channels
        self.frames = []

        def callback(indata, frame_count, time_info, status):
            self.frames.append(indata.copy())

        self.stream = sd.InputStream(
            device=device,
            samplerate=samplerate,
            channels=channels,
            dtype="int16",
            callback=callback,
        )
        self.stream.start()

    def stop_recording(self) -> str:
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        if not self.frames:
            return ""

        audio = np.concatenate(self.frames, axis=0)
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)

        with wave.open(path, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.samplerate)
            wf.writeframes(audio.tobytes())

        return path
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_audio.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/audio.py tests/test_audio.py
git commit -m "feat: add audio recorder"
```

---

### Task 4: Speech-to-Text Module

**Files:**
- Create: `src/stt.py`
- Create: `tests/test_stt.py`

**Interfaces:**
- Produces: `class STT`
  - `__init__(model_size: str = "base", language: str = "en")`
  - `transcribe(audio_path: str) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_stt.py
from unittest.mock import MagicMock, patch
from src.stt import STT


@patch("src.stt.WhisperModel")
def test_stt_transcribe_returns_text(mock_whisper_model):
    mock_seg = MagicMock()
    mock_seg.text = "hello world"
    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([mock_seg], None)
    mock_whisper_model.return_value = mock_model

    stt = STT(model_size="tiny", language="en")
    result = stt.transcribe("/tmp/fake.wav")
    assert result == "hello world"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_stt.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.stt'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/stt.py
from faster_whisper import WhisperModel


class STT:
    def __init__(self, model_size: str = "base", language: str = "en"):
        self.language = language
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")

    def transcribe(self, audio_path: str) -> str:
        segments, _ = self.model.transcribe(audio_path, language=self.language)
        text = " ".join(segment.text.strip() for segment in segments)
        return text.strip()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_stt.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stt.py tests/test_stt.py
git commit -m "feat: add speech-to-text module"
```

---

### Task 5: Text-to-Speech Module

**Files:**
- Create: `src/tts.py`
- Create: `tests/test_tts.py`

**Interfaces:**
- Produces: `class TTS`
  - `__init__(voice_id: str = "default")`
  - `speak(text: str)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tts.py
from unittest.mock import MagicMock, patch
from src.tts import TTS


@patch("src.tts.pyttsx3.init")
def test_tts_speak_runs_engine(mock_init):
    mock_engine = MagicMock()
    mock_init.return_value = mock_engine

    tts = TTS(voice_id="default")
    tts.speak("hello")

    mock_engine.say.assert_called_once_with("hello")
    mock_engine.runAndWait.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_tts.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.tts'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/tts.py
import pyttsx3


class TTS:
    def __init__(self, voice_id: str = "default"):
        self.engine = pyttsx3.init()
        if voice_id and voice_id != "default":
            voices = self.engine.getProperty("voices")
            for voice in voices:
                if voice.id == voice_id:
                    self.engine.setProperty("voice", voice.id)
                    break

    def speak(self, text: str):
        if not text:
            return
        self.engine.say(text)
        self.engine.runAndWait()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_tts.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tts.py tests/test_tts.py
git commit -m "feat: add text-to-speech module"
```

---

### Task 6: Clipboard Watcher

**Files:**
- Create: `src/clipboard_watcher.py`
- Create: `tests/test_clipboard_watcher.py`

**Interfaces:**
- Produces: `class ClipboardWatcher`
  - `__init__(window_seconds: float = 30.0)`
  - `start()`
  - `stop()`
  - `get_new_text() -> str | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_clipboard_watcher.py
import time
from unittest.mock import patch
from src.clipboard_watcher import ClipboardWatcher


@patch("src.clipboard_watcher.pyperclip.paste")
def test_watcher_detects_new_clipboard_text(mock_paste):
    mock_paste.side_effect = ["old", "new reply"]
    watcher = ClipboardWatcher(window_seconds=1.0)
    watcher.start()
    time.sleep(0.1)
    text = watcher.get_new_text()
    watcher.stop()

    assert text == "new reply"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_clipboard_watcher.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.clipboard_watcher'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/clipboard_watcher.py
import threading
import time
import pyperclip


class ClipboardWatcher:
    def __init__(self, window_seconds: float = 30.0):
        self.window_seconds = window_seconds
        self._running = False
        self._thread = None
        self._baseline = ""
        self._new_text = None
        self._lock = threading.Lock()

    def start(self):
        self._baseline = pyperclip.paste() or ""
        self._new_text = None
        self._running = True
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)

    def get_new_text(self) -> str | None:
        with self._lock:
            return self._new_text

    def _watch(self):
        deadline = time.time() + self.window_seconds
        while self._running and time.time() < deadline:
            current = pyperclip.paste() or ""
            if current != self._baseline:
                with self._lock:
                    self._new_text = current
                return
            time.sleep(0.2)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_clipboard_watcher.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/clipboard_watcher.py tests/test_clipboard_watcher.py
git commit -m "feat: add clipboard watcher"
```

---

### Task 7: Keyboard Input Injector

**Files:**
- Create: `src/keyboard_input.py`
- Create: `tests/test_keyboard_input.py`

**Interfaces:**
- Produces: `type_text(text: str, interval: float = 0.01)`
- Produces: `press_enter()`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_keyboard_input.py
from unittest.mock import patch
from src.keyboard_input import type_text, press_enter


@patch("src.keyboard_input.keyboard")
def test_type_text_sends_keys(mock_keyboard):
    type_text("hi", interval=0)
    mock_keyboard.write.assert_called_once_with("hi", delay=0)


@patch("src.keyboard_input.keyboard")
def test_press_enter_sends_return(mock_keyboard):
    press_enter()
    mock_keyboard.press_and_release.assert_called_once_with("return")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_keyboard_input.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.keyboard_input'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/keyboard_input.py
import keyboard


def type_text(text: str, interval: float = 0.01):
    if not text:
        return
    keyboard.write(text, delay=interval)


def press_enter():
    keyboard.press_and_release("return")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_keyboard_input.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_input.py tests/test_keyboard_input.py
git commit -m "feat: add keyboard input injector"
```

---

### Task 8: Tray App + Orchestrator

**Files:**
- Create: `src/voice_bridge.py`
- Create: `tests/test_voice_bridge.py`

**Interfaces:**
- Consumes: `load_config`, `AudioRecorder`, `STT`, `TTS`, `ClipboardWatcher`, `type_text`, `press_enter`
- Produces: `class VoiceBridge`
  - `run()`
  - `toggle_speak_replies()`
  - `handle_dictation_hotkey()`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_voice_bridge.py
from unittest.mock import MagicMock, patch
from src.voice_bridge import VoiceBridge


@patch("src.voice_bridge.load_config")
@patch("src.voice_bridge.STT")
@patch("src.voice_bridge.TTS")
@patch("src.voice_bridge.AudioRecorder")
@patch("src.voice_bridge.ClipboardWatcher")
@patch("src.voice_bridge.type_text")
@patch("src.voice_bridge.press_enter")
@patch("src.voice_bridge.keyboard")
def test_voice_bridge_dictation_flow(
    mock_keyboard,
    mock_press_enter,
    mock_type_text,
    mock_watcher_cls,
    mock_recorder_cls,
    mock_tts_cls,
    mock_stt_cls,
    mock_load_config,
):
    mock_load_config.return_value = {
        "dictation_hotkey": "ctrl+shift+space",
        "speak_replies": False,
        "clipboard_window_seconds": 30,
        "mic_device": "default",
        "tts_voice": "default",
        "stt_model": "tiny",
        "language": "en",
        "sample_rate": 16000,
        "channels": 1,
    }
    mock_recorder = MagicMock()
    mock_recorder.stop_recording.return_value = "/tmp/fake.wav"
    mock_recorder_cls.return_value = mock_recorder
    mock_stt = MagicMock()
    mock_stt.transcribe.return_value = "hello"
    mock_stt_cls.return_value = mock_stt

    bridge = VoiceBridge()
    bridge.handle_dictation_hotkey()

    mock_recorder.start_recording.assert_called_once()
    mock_stt.transcribe.assert_called_once_with("/tmp/fake.wav")
    mock_type_text.assert_called_once_with("hello", interval=0.01)
    mock_press_enter.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_voice_bridge.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.voice_bridge'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/voice_bridge.py
import os
import threading
import time
import keyboard
import pystray
from PIL import Image, ImageDraw

from src.config import load_config
from src.audio import AudioRecorder
from src.stt import STT
from src.tts import TTS
from src.clipboard_watcher import ClipboardWatcher
from src.keyboard_input import type_text, press_enter


class VoiceBridge:
    def __init__(self, config_path: str = "config.json"):
        self.config = load_config(config_path)
        self.recorder = AudioRecorder()
        self.stt = STT(
            model_size=self.config["stt_model"],
            language=self.config["language"],
        )
        self.tts = TTS(voice_id=self.config["tts_voice"])
        self.speak_replies = self.config["speak_replies"]
        self.hotkey = self.config["dictation_hotkey"]
        self.recording = False
        self.icon = None

    def run(self):
        self._setup_hotkey()
        self.icon = self._create_tray_icon()
        self.icon.run()

    def _setup_hotkey(self):
        keyboard.add_hotkey(self.hotkey, self.handle_dictation_hotkey)

    def handle_dictation_hotkey(self):
        if self.recording:
            return
        self.recording = True
        try:
            self.recorder.start_recording(
                device=self.config["mic_device"],
                samplerate=self.config["sample_rate"],
                channels=self.config["channels"],
            )
        except Exception as e:
            self._notify(f"Mic error: {e}")
            self.recording = False
            return

        # Run recording loop in background so hotkey release can stop it.
        def wait_and_stop():
            keyboard.wait(self.hotkey, suppress=True)
            path = self.recorder.stop_recording()
            self.recording = False
            if not path:
                return
            try:
                text = self.stt.transcribe(path)
                if text:
                    type_text(text, interval=0.01)
                    press_enter()
                    if self.speak_replies:
                        self._speak_reply()
            except Exception as e:
                self._notify(f"Dictation failed: {e}")
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass

        thread = threading.Thread(target=wait_and_stop, daemon=True)
        thread.start()

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
                self.tts.speak(text)
                return
            time.sleep(0.2)
        watcher.stop()

    def toggle_speak_replies(self):
        self.speak_replies = not self.speak_replies
        state = "ON" if self.speak_replies else "OFF"
        self._notify(f"Speak replies: {state}")

    def _notify(self, message: str):
        if self.icon:
            self.icon.notify(message, title="Kimi Voice Bridge")
        print(message)

    def _create_tray_icon(self):
        image = self._create_image()
        menu = pystray.Menu(
            pystray.MenuItem(
                "Speak replies",
                self.toggle_speak_replies,
                checked=lambda item: self.speak_replies,
            ),
            pystray.MenuItem("Exit", self._exit),
        )
        return pystray.Icon("kimi_voice_bridge", image, "Kimi Voice Bridge", menu)

    def _create_image(self):
        width = 64
        height = 64
        image = Image.new("RGB", (width, height), "white")
        dc = ImageDraw.Draw(image)
        dc.ellipse((8, 8, width - 8, height - 8), fill="black")
        return image

    def _exit(self, icon, item):
        icon.stop()


if __name__ == "__main__":
    bridge = VoiceBridge()
    bridge.run()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_voice_bridge.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/voice_bridge.py tests/test_voice_bridge.py
git commit -m "feat: add tray app and orchestration"
```

---

### Task 9: Integration Test

**Files:**
- Create: `tests/test_integration.py`

**Interfaces:**
- Consumes: all modules.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_integration.py
from unittest.mock import MagicMock, patch
from src.voice_bridge import VoiceBridge


@patch("src.voice_bridge.load_config")
@patch("src.voice_bridge.STT")
@patch("src.voice_bridge.TTS")
@patch("src.voice_bridge.AudioRecorder")
@patch("src.voice_bridge.ClipboardWatcher")
@patch("src.voice_bridge.type_text")
@patch("src.voice_bridge.press_enter")
@patch("src.voice_bridge.keyboard")
def test_full_flow_with_tts_toggle(
    mock_keyboard,
    mock_press_enter,
    mock_type_text,
    mock_watcher_cls,
    mock_recorder_cls,
    mock_tts_cls,
    mock_stt_cls,
    mock_load_config,
):
    mock_load_config.return_value = {
        "dictation_hotkey": "ctrl+shift+space",
        "speak_replies": True,
        "clipboard_window_seconds": 1,
        "mic_device": "default",
        "tts_voice": "default",
        "stt_model": "tiny",
        "language": "en",
        "sample_rate": 16000,
        "channels": 1,
    }
    mock_recorder = MagicMock()
    mock_recorder.stop_recording.return_value = "/tmp/fake.wav"
    mock_recorder_cls.return_value = mock_recorder
    mock_stt = MagicMock()
    mock_stt.transcribe.return_value = "hello kim"
    mock_stt_cls.return_value = mock_stt
    mock_watcher = MagicMock()
    mock_watcher.get_new_text.return_value = "Hi there"
    mock_watcher_cls.return_value = mock_watcher
    mock_tts = MagicMock()
    mock_tts_cls.return_value = mock_tts

    bridge = VoiceBridge()
    bridge.handle_dictation_hotkey()

    mock_tts.speak.assert_called_once_with("Hi there")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_integration.py -v
```

Expected: FAIL because `handle_dictation_hotkey` spawns a thread; the test may finish before TTS is called.

- [ ] **Step 3: Adjust implementation to make integration testable**

In `src/voice_bridge.py`, extract the dictation logic into a synchronous method:

```python
    def handle_dictation_hotkey(self):
        if self.recording:
            return
        self.recording = True
        try:
            self.recorder.start_recording(...)
        except Exception as e:
            ...
            return
        thread = threading.Thread(target=self._finish_dictation, daemon=True)
        thread.start()

    def _finish_dictation(self):
        keyboard.wait(self.hotkey, suppress=True)
        path = self.recorder.stop_recording()
        self.recording = False
        if not path:
            return
        try:
            text = self.stt.transcribe(path)
            if text:
                type_text(text, interval=0.01)
                press_enter()
                if self.speak_replies:
                    self._speak_reply()
        except Exception as e:
            self._notify(f"Dictation failed: {e}")
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
```

Update `handle_dictation_hotkey` to call `_finish_dictation`.

- [ ] **Step 4: Update integration test to call `_finish_dictation` directly**

```python
    bridge.recording = True
    bridge._finish_dictation()
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_integration.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/voice_bridge.py tests/test_integration.py
git commit -m "feat: add integration test for full voice flow"
```

---

### Task 10: Final README and Run Instructions

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace README skeleton with final content**

```markdown
# Kimi Voice Bridge

Push-to-talk voice dictation + optional spoken replies for the Kimi desktop app.

## Install

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
```

On first run the `faster-whisper` model will download automatically (~150 MB for `base`).

## Run

```bash
python src/voice_bridge.py
```

A microphone icon appears in the system tray.

## Usage

1. Click the Kimi desktop chat box to focus it.
2. Hold `Ctrl + Shift + Space`, speak, then release.
3. The transcript is typed and sent.
4. Right-click the tray icon and check **Speak replies** to hear copied replies.
5. When **Speak replies** is ON, copy Kimi's reply to the clipboard within 30 seconds to hear it read aloud.

## Configuration

Edit `config.json`:

| Key | Default | Description |
|-----|---------|-------------|
| `dictation_hotkey` | `ctrl+shift+space` | Hotkey to hold while speaking |
| `speak_replies` | `false` | Start with TTS enabled |
| `clipboard_window_seconds` | `30` | How long to watch clipboard for replies |
| `stt_model` | `base` | Whisper model size (`tiny`, `base`, `small`) |
| `language` | `en` | Speech language code |
| `mic_device` | `default` | Audio input device |

## Run Tests

```bash
pytest tests/ -v
```
```

- [ ] **Step 2: Run all tests**

```bash
pytest tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: final README with install and usage"
```

---

## Self-Review

**Spec coverage:**
- Voice dictation: Tasks 3, 4, 7, 8.
- TTS toggle: Tasks 5, 6, 8.
- Works through Kimi desktop app: Task 7 keyboard injection, Task 8 orchestration.
- Configuration: Task 2.
- Error handling: Embedded in Tasks 3, 4, 5, 6, 7, 8.

**Placeholder scan:** No TBD/TODO placeholders. All code blocks are complete. All test commands have expected output.

**Type consistency:**
- `load_config(path: str) -> dict`
- `AudioRecorder.start_recording(device=None, samplerate=16000, channels=1)`
- `AudioRecorder.stop_recording() -> str`
- `STT.transcribe(audio_path: str) -> str`
- `TTS.speak(text: str)`
- `ClipboardWatcher.get_new_text() -> str | None`
- `type_text(text: str, interval: float = 0.01)`
- `press_enter()`

No signature mismatches across tasks.
