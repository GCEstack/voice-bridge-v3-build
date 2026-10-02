# Kimi Voice Bridge + Deepgram Voice Merge

**Date:** 2026-07-22  
**Goal:** Replace `kimi-voice-bridge`'s local Whisper STT with the Deepgram-based dictation pipeline from `C:\Lares_Family\Tools\voice`, while keeping the bridge's tray UI, global hotkey, and "Speak replies" TTS.

---

## 1. Problem

There are two separate voice systems:

1. **Deepgram voice dictation** (`C:\Lares_Family\Tools\voice`) — always-on, types into any focused window, uses Deepgram Nova-2/3, has a rich voice profile + command set.
2. **Kimi Voice Bridge** (`kimi-voice-bridge`) — push-to-talk, local Whisper, types into Kimi Desktop, has a tray icon and spoken-reply TTS.

The user wants one system with the bridge's UI and the Deepgram engine + profile/commands.

---

## 2. Solution Overview

Keep `kimi-voice-bridge`'s tray app skeleton, replace its STT stack with the Deepgram pipeline, and wire in the existing voice profile and command parser.

```
Mic ──▶ DeepgramCapture ──▶ speech_corrector ──▶ voice_command_parser
                                    │                      │
                                    ▼                      ▼
                           corrected text            hotkey action
                                    │                      │
                                    └──────▶ type into focused window
```

---

## 3. Components

| File | Responsibility |
|------|----------------|
| `src/voice_bridge.py` | Tray icon, global hotkey, orchestration, config loading. Replaces `AudioRecorder` + `STT` with `DeepgramCapture`. |
| `src/capture.py` | Copied from `C:\Lares_Family\Tools\voice\capture.py`. Deepgram WebSocket streaming. |
| `src/speech_corrector.py` | Copied from `C:\Lares_Family\Tools\voice\speech_corrector.py`. Applies voice-profile corrections. |
| `src/voice_commands.py` | Extracted from `C:\Lares_Family\Tools\voice\voice_access.py`. Parses and executes voice commands. |
| `src/tts.py` | Kept from existing bridge. Speaks replies. |
| `src/clipboard_watcher.py` | Kept from existing bridge. Watches clipboard for replies. |
| `src/audio.py` | Removed — no longer needed with streaming Deepgram capture. |
| `src/stt.py` | Removed — no longer needed. |
| `voice-profile.json` | Copied from `C:\Lares_Family\Tools\voice\voice-profile.json` (or loaded from `~/.kimi-code/voice-profile.json`). |
| `markers.json` | Copied from Deepgram project; used by `speech_corrector`. |
| `corrections.json` | Copied from Deepgram project; used by `speech_corrector`. |
| `config.json` | Existing bridge config plus `deepgram_api_key` and `voice_profile_path`. |

---

## 4. Data Flow

1. User holds push-to-talk hotkey (`Ctrl+Shift+Space` by default).
2. `voice_bridge.py` starts `DeepgramCapture` streaming to Deepgram.
3. User speaks and releases the hotkey.
4. `voice_bridge.py` stops capture, waits for final transcript.
5. Final raw transcript is passed to `speech_corrector.apply_corrections()`.
6. Corrected text is passed to `voice_commands.handle_command()`.
7. If it's a command, execute it; otherwise type the corrected text into the focused window.
8. If "Speak replies" is ON, start clipboard watcher and read any copied reply aloud via TTS.

---

## 5. Configuration

`config.json` additions:

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

- If `deepgram_api_key` is empty, load from `DEEPGRAM_API_KEY` env var or `.env`.
- If `voice_profile_path` is empty, default to `~/.kimi-code/voice-profile.json`, then fallback to local `voice-profile.json`.

---

## 6. Error Handling

| Scenario | Behavior |
|----------|----------|
| Deepgram auth fails | Tray notification: "Deepgram API key rejected. Check config.json or .env." |
| No mic / audio error | Tray notification, stop capture, reset state. |
| STT returns empty | Do nothing. |
| Corrector throws | Log error, fall back to raw transcript. |
| Command parser throws | Log error, type corrected text instead. |

---

## 7. Testing Plan

1. **Unit tests:** `speech_corrector` profile corrections already pass; add tests for `voice_commands` and `voice_bridge` orchestration.
2. **Integration test:** Mock `DeepgramCapture`, simulate hotkey press/release + final transcript, assert corrected text is typed.
3. **Manual test:** Hold hotkey, speak "open Kimi", release → corrected text appears in focused window. Toggle "Speak replies", copy text → TTS plays.

---

## 8. Out of Scope

- Real-time streaming interim transcripts displayed in UI.
- macOS port.
- Always-on listening mode (push-to-talk only).
- New voice commands beyond what already exists in `voice_access.py`.
