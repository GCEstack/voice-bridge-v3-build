# VoiceBridge — Live Spec (Internal / Coda)

**Status:** current live architecture (supersedes the 07-15 push-to-talk and 07-22 Deepgram
designs; those are preserved as provenance under `docs\superpowers\`).
**Operator lineage:** Kimi → Keel → Talon (see A31 — launcher rename pending).

---

## 1. What it is

A **wake-word, always-on voice layer** for the desktop. It listens continuously, and only
types or executes when you say a wake word. No hotkey to hold. It replaces the older
push-to-talk (`Ctrl+Shift+Space`) model.

- **STT engine:** AssemblyAI **Universal-3.5 Pro** (`universal-3-5-pro`) streaming.
- **Input path:** Mic → AssemblyAI (always-on) → finalized turn → `_handle_final()` →
  wake-word gate → ARM / type / command.
- **Output path:** keyboard injection into the **focused window**; optional "Speak replies"
  TTS for copied replies.

## 2. Core mechanics (state machine)

- **SLEEPING (default).** Finalized transcripts are scanned for a wake word; ambient speech
  is ignored (never typed). Saying a wake word **ARMs** the bridge.
- **ARMED.** Subsequent utterances are typed verbatim (or executed as commands) until a
  sleep command (`stop listening` / `sleep`) or the idle timeout.
- **Single-instance.** A named mutex prevents duplicate-process / fighting-mic — the failure
  that bricked the old launcher.
- **No correction pass.** The raw engine transcript is typed verbatim. Accuracy is improved
  **at the source** via `keyterms_prompt` (custom vocabulary, max 100). Wake words are
  auto-merged into `keyterms` so the engine spells them.

## 3. Data flow

```
Mic -> AssemblyAI (always-on) -> finalized Turn -> _handle_final()
   |                                              |
   |  keyterms_prompt preload (names + wake words) v
   |                                  wake word? -> ARM / type / command
   |                                  else ignore (SLEEPING)
```

## 4. Voice commands (matched as exact phrase while ARMED)

- **Editing:** `copy that`, `paste it`, `cut that`, `select all`, `undo`, `redo`, `save`,
  `new line`, `delete word`, `clear all`, `cancel that`
- **Punctuation:** `period`, `comma`, `question mark`, `exclamation mark`, `quote`, `colon`,
  `semicolon`, `tab`, `space`
- **Navigation:** `up`, `down`, `left`, `right`, `page up`, `page down`, `go back`,
  `go forward`, `refresh`, `find`
- **Window/app:** `new tab`, `close tab`, `new window`, `reopen tab`, `alt tab`,
  `close window`, `minimize`, `maximize`, `show desktop`, `task view`
- **Session:** `sleep` (pause), `wake up` (resume), `quit`

> **Command semantics (Don approved 2026-09-25).** `sleep` / `wake up` are exact
> whole-utterance commands only — no prefix matching. `stop listening` and `start listening`
> are **no longer commands**; both are normal dictation. Self-test checks 14/26 cover this.

## 5. Handoff review queue (internal wiring)

The control window includes a **handoff review queue** — a read-only panel that renders
resolved handoffs for Don/Coda review. The record registry is one JSON file per handoff,
path configured in `config.json` under `handoff_queue.registry_path` (defaults to
`voice-bridge\queue\`). The schema and writer ownership are documented in
`queue\README.md`.

Actions: **Open** (`os.startfile` on the local artifact), **Copy Text** (metadata header +
body), **Copy Path**, **Dismiss**. Dismiss writes only the panel's own reviewer state
(`handoff_queue.local_state`) and **never** mutates `status` in the registry.

**Boundary:** VoiceBridge is the review surface, not the transport layer. It never creates,
routes, claims or mutates a handoff record, and it owns no department destinations. The
legacy `queue_sources` / `route_buttons` intake-crawl + `route_note()` writer were removed
2026-09-26 (Nico strategy E) because they made VoiceBridge a producer and gave it routing
semantics. A missing registry shows as `registry offline` and is never auto-created.
The registry path must be a **local** folder — never a Drive mount (Drive is reached through
the Cable Car API path, never a synchronous scan on the Tk thread).

## 6. Config (`config.json`) — current keys

| Key | Default | Description |
|-----|---------|-------------|
| `mode` | `wake_word` | `wake_word` (always-on, hands-free) or `push_to_talk` (legacy) |
| `wake_words` | `["hey keel","ok keel","okay keel","keel"]` | Phrases that arm the bridge |
| `armed_timeout_seconds` | `12` | Auto-sleep after this many seconds idle while ARMED |
| `assemblyai_api_key` | `""` | AssemblyAI key (or `ASSEMBLYAI_API_KEY` env var) |
| `speech_model` | `universal-3-5-pro` | Streaming model |
| `keyterms` | name list | Custom vocabulary via `keyterms_prompt` (max 100) |
| `mic_device` | `default` | Audio input device |
| `sample_rate` | `16000` | PCM sample rate to AssemblyAI |
| `channels` | `1` | Audio channels |
| `handoff_queue.registry_path` | `voice-bridge\queue` | Handoff review registry (local folder, READ-only) |
| `handoff_queue.refresh_seconds` | `30` | Queue auto-refresh cadence |
| `handoff_queue.limit` | `300` | Max records rendered |
| `handoff_queue.local_state` | `voice-bridge\queue_local.json` | Panel's own reviewer state (dismissals) |

Removed keys: `speak_replies`, `clipboard_window_seconds`, `queue_sources`,
`route_buttons`, `queue_refresh_seconds` — the first two with the TTS/clipboard-watcher
simplification, the last three with the review-surface rebuild (2026-09-26).

## 7. Run

```bash
python -m src.voice_bridge             # GUI, always-on wake word
python -m src.voice_bridge --self-test # headless state-machine check, no mic
```

A small control window stays on top showing `SLEEPING` / `ARMED` and last status, with
Arm / Sleep / Quit buttons.

## 8. Tests

```bash
.venv\Scripts\python -m pytest tests/ -v
.venv\Scripts\python -m src.voice_bridge --self-test
```

## 9. Notes / open items

- **Wake-word = LEGACY ARCHITECTURE (2026-09-02).** `'hey keel'` is the old design for
  bouncing across terminal windows; to be REVISITED under the new orchestrator + framework
  (Don). Do not invest in the current wake-word architecture.
- Continuous streaming incurs AssemblyAI usage; a local VAD pre-filter to gate silent audio
  is a planned follow-up.
- Keyboard injection types into the focused window — target focus is the whole control model.
- Config file carries an internal `_note_wake_words` annotation reflecting the above.
