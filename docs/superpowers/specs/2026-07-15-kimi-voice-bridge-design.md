# Kimi Voice Bridge — Design Spec

**Date:** 2026-07-15  
**Goal:** Add seamless voice dictation and optional spoken replies to the Kimi desktop app via a local helper.  
**Scope:** MVP that can be built and run tonight on Windows/macOS.

---

## 1. Problem Statement

The Kimi desktop app does not expose a public API or plugin surface for voice input/output. The user wants:

1. **Always-available voice dictation** — speak, and the transcript appears in Kimi's chat input.
2. **TTS toggle** — a switch that controls whether Kimi's reply is read aloud.
3. **Works through the desktop app** — the conversation itself still happens inside Kimi Desktop; the helper only adds the voice layer.

## 2. Solution Overview

Build a lightweight **system-tray helper** called **Kimi Voice Bridge** that runs alongside the Kimi desktop app.

- Captures microphone audio on a global hotkey.
- Transcribes audio to text using a local STT engine.
- Injects the transcribed text into the Kimi chat input and presses Enter.
- Monitors the clipboard for copied replies and speaks them when the TTS toggle is ON.

This avoids fighting the Kimi desktop app's internals and can be assembled in a single evening.

## 3. User Experience

### 3.1 Voice Dictation
1. User focuses the Kimi desktop chat window (clicks once).
2. User holds the dictation hotkey (default `Ctrl + Shift + Space`).
3. A small overlay/toast shows "Listening...".
4. User releases the hotkey.
5. The helper transcribes the audio, types it into the Kimi chat box, and sends Enter.

### 3.2 TTS Toggle
- A tray menu item labeled **"Speak replies"** toggles ON/OFF.
- When ON, copying any text to the clipboard within 30 seconds after a voice send causes the helper to read it aloud.
- When OFF, clipboard is ignored.

### 3.3 Settings
- Hotkey for dictation.
- Microphone device selection.
- TTS voice selection (system voices).
- Clipboard monitoring window (default 30 s after send).

## 4. Architecture

```
┌─────────────────┐      ┌──────────────────┐      ┌─────────────────┐
│   Microphone    │──────▶│   STT Engine     │──────▶│  Keyboard Input │──────▶ Kimi Desktop
│  (hotkey start) │      │ (Whisper / OS)   │      │  (type + Enter) │
└─────────────────┘      └──────────────────┘      └─────────────────┘
                                                              │
                                                              │ reply appears
                                                              ▼
┌─────────────────┐      ┌──────────────────┐      ┌─────────────────┐
│  System TTS     │◀─────│  Clipboard Watch │◀─────│  User copies    │
│  (pyttsx3)      │      │  (toggle ON)     │      │  Kimi reply     │
└─────────────────┘      └──────────────────┘      └─────────────────┘
```

## 5. Components

| File | Responsibility |
|------|----------------|
| `voice_bridge.py` | Tray icon, global hotkeys, orchestration, config loading |
| `stt.py` | Record audio, run STT, return text |
| `tts.py` | Speak text using system TTS |
| `clipboard_watcher.py` | Watch clipboard for new text during monitoring window |
| `config.json` | User settings (hotkeys, mic, voice, delays) |
| `README.md` | Install and run instructions |

## 6. Tech Stack

- **Language:** Python 3.11+
- **Audio capture:** `sounddevice` or `pyaudio`
- **STT:** `faster-whisper` (local) with `speech_recognition` fallback
- **Keyboard injection:** `keyboard` (Windows) / `pynput` (cross-platform)
- **TTS:** `pyttsx3`
- **Tray icon:** `pystray`
- **Clipboard:** `pyperclip`

## 7. Data Flow

1. Hotkey pressed → start recording from selected mic.
2. Hotkey released → stop recording, save to temp WAV.
3. Run STT on WAV → produce text string.
4. If text is non-empty:
   a. Type text into currently focused window.
   b. Press Enter.
   c. Start 30-second clipboard monitoring window.
5. If TTS toggle is ON and clipboard receives new text during the window, call `tts.speak(text)`.

## 8. Error Handling

| Scenario | Behavior |
|----------|----------|
| STT returns empty | Do nothing; log at debug level. |
| Keyboard injection fails | Show tray notification: "Could not type into Kimi. Is the chat box focused?" |
| TTS fails | Log error; continue without audio for that reply. |
| Mic unavailable | Show tray notification and exit recording. |
| No audio captured | Ignore and reset state. |

## 9. Configuration Defaults

```json
{
  "dictation_hotkey": "ctrl+shift+space",
  "speak_replies": false,
  "clipboard_window_seconds": 30,
  "mic_device": "default",
  "tts_voice": "default",
  "stt_model": "base",
  "language": "en"
}
```

## 10. Testing Plan

1. **Dictation test:** Hold hotkey, speak, release → text appears in Kimi and message sends.
2. **Toggle ON test:** Copy a Kimi reply → audio plays.
3. **Toggle OFF test:** Copy a Kimi reply → no audio plays.
4. **Hotkey change test:** Modify `config.json`, restart helper, verify new hotkey works.
5. **Empty audio test:** Tap hotkey without speaking → no text injected.

## 11. Future Migration Path

Once Kimi Claw exposes a proper voice/skill API, the STT/TTS modules can be repackaged as a Claw skill or plugin. The orchestration logic in `voice_bridge.py` maps cleanly to a `SKILL.md` instruction set, and `stt.py`/`tts.py` become tool wrappers.

## 12. Out of Scope

- Real-time streaming STT (full sentence only after release).
- Reading Kimi replies without user copying them.
- Native Kimi Claw plugin packaging tonight.
- Mobile or browser support.
