# Keel Voice Bridge

Hands-free, **wake-word** voice dictation + optional spoken replies, on
**AssemblyAI Universal-3.5 Pro** (`universal-3-5-pro`) streaming. No hotkey to
hold â€” the mic listens continuously; nothing is typed until you say a wake word.
Replaces the earlier push-to-talk (hold `Ctrl+Shift+Space`) model.

## How it works

```
Mic -> AssemblyAI (always-on) -> finalized Turn -> _handle_final()
   |                                              |
   |  keyterms_prompt preload (Kimi, GLM, EC4,    v
   |  EC8, Vela, Claude, Renzo, Santonio,   wake word? -> ARM / type / command
   |  + the wake words themselves)           else ignore (SLEEPING)
```

- **Wake-word gated.** While `SLEEPING`, finalized transcripts are scanned for a
  wake word and otherwise ignored (ambient speech is not typed). Saying a wake
  word `ARM`s the bridge.
- **Armed.** Subsequent utterances are typed verbatim (or executed as commands)
  until the pause command (`sleep`) or the idle timeout.
- **Single-instance.** A named mutex prevents the duplicate-process /
  fighting-mic problem that bricked the old launcher.
- **Engine accuracy is improved at the source** via `keyterms_prompt`. There is
  **no correction/proofreading pass** â€” the raw engine transcript is typed
  verbatim. Wake words are auto-merged into `keyterms` so the engine spells them.

## Install

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

## Configure

Set your AssemblyAI API key in `config.json` or via an environment variable:

```bash
# .env
ASSEMBLYAI_API_KEY=your-key-here
```

`config.json`:

| Key | Default | Description |
|-----|---------|-------------|
| `mode` | `wake_word` | `wake_word` (always-on, hands-free) or `push_to_talk` (legacy) |
| `wake_words` | `["hey keel","ok keel","okay keel","keel"]` | Phrases that arm the bridge |
| `armed_timeout_seconds` | `12` | Auto-sleep after this many seconds idle while ARMED |
| `speak_replies` | `false` | Read copied replies aloud via TTS |
| `clipboard_window_seconds` | `30` | How long to watch clipboard for replies |
| `assemblyai_api_key` | `""` | AssemblyAI API key (or use `ASSEMBLYAI_API_KEY` env var) |
| `speech_model` | `universal-3-5-pro` | Streaming model |
| `keyterms` | name list | Custom vocabulary preloaded via `keyterms_prompt` (max 100) |
| `mic_device` | `default` | Audio input device |
| `sample_rate` | `16000` | PCM sample rate sent to AssemblyAI |
| `channels` | `1` | Audio channels |

## Run

```bash
python -m src.voice_bridge             # GUI, always-on wake word
python -m src.voice_bridge --self-test # headless state-machine check, no mic
```

A small control window appears and stays on top, showing `SLEEPING` / `ARMED`
and the last status. Buttons let you manually Arm / Sleep / Quit.

## Usage

1. Click the window you want to type into.
2. Say a wake word, then your text â€” e.g. *"hey keel, open the notion board."*
3. The wake word is stripped and the rest is typed (no auto-Enter). You're now ARMED.
4. Say **"enter"** / **"send"** when you want to press Return, or press it yourself.
4. Keep talking; each utterance is typed until you say **"sleep"**
   (or go quiet for ~12s), which returns the bridge to SLEEPING.

## Voice commands

Say these while ARMED (matched as exact phrase):

- **Editing:** `copy that`, `paste it`, `cut that`, `select all`, `undo`, `redo`, `save`, `new line`, `delete word`, `clear all`, `cancel that`
- **Punctuation:** `period`, `comma`, `question mark`, `exclamation mark`, `quote`, `colon`, `semicolon`, `tab`, `space`
- **Navigation:** `up`, `down`, `left`, `right`, `page up`, `page down`, `go back`, `go forward`, `refresh`, `find`
- **Window/app:** `new tab`, `close tab`, `new window`, `reopen tab`, `alt tab`, `close window`, `minimize`, `maximize`, `show desktop`, `task view`
- **Session:** `sleep` (pause) / `wake up` (resume) — exact whole utterance only, no prefix matching — `quit`

## Run tests

```bash
.venv\Scripts\python -m pytest tests/ -v
.venv\Scripts\python -m src.voice_bridge --self-test
```

## Notes

- The helper uses keyboard injection to type into the focused window.
- The bridge streams to AssemblyAI whenever the mic hears speech (always-on).
  Continuous streaming incurs AssemblyAI usage; a local VAD pre-filter to gate
  silent audio is a planned follow-up.
