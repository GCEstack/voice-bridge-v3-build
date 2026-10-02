# VoiceBridge — Spec (Shareable)

A **wake-word, always-on voice layer** for the desktop. It listens continuously and only
types or executes when you say a wake word. No hotkey to hold.

This is a working reference for anyone building a **voice-driven orchestrator** — a layer
you can talk to that sees/controls the rest of your setup — because that's exactly what this
tool is: a persistent voice front-end that drives whatever window is in focus.

---

## Core idea

```
Mic -> STT engine (always-on) -> finalized transcript -> wake-word gate
   |                                                       |
   |  custom vocabulary preloaded into the engine          v
   |                              wake word? -> ARM -> type / run command
   |                              else -> ignore (ambient speech not typed)
```

- **Always listening, never intrusive.** While idle, ambient speech is ignored. Saying a
  wake word "arms" it.
- **Types into whatever is focused.** Once armed, your speech becomes keystrokes in the
  active window — any app, not just one.
- **Command layer.** In addition to free dictation, exact spoken phrases trigger editing,
  navigation, and window/app actions (see below).
- **Optional spoken replies.** When enabled, text you copy is read back to you via TTS.

## Key design choices

- **Wake-word gated** — so it doesn't type random conversation.
- **Single-instance** (named mutex) — prevents duplicate processes fighting over the mic,
  which had previously bricked an older launcher.
- **Accuracy handled at the source** — a custom-vocabulary prompt (`keyterms`, up to 100
  terms) is preloaded into the STT engine so names and domain terms are spelled correctly.
  No fragile post-correction pass; raw transcript is used as-is.
- **Push-to-talk also supported** as a legacy mode — some users prefer hold-to-talk over
  always-on.
- **Session control by voice** — `stop listening` disarms, `wake up` re-arms, `quit` exits.

## Voice commands (spoken while armed)

- **Editing:** copy that · paste it · cut that · select all · undo · redo · save · new line ·
  delete word · clear all · cancel that
- **Punctuation:** period · comma · question mark · exclamation mark · quote · colon ·
  semicolon · tab · space
- **Navigation:** up · down · left · right · page up · page down · go back · go forward ·
  refresh · find
- **Window/app:** new tab · close tab · new window · reopen tab · alt tab · close window ·
  minimize · maximize · show desktop · task view
- **Session:** sleep · wake up · quit

## Architecture notes for someone building their own

- **STT engine is pluggable.** The current build uses a cloud streaming STT model
  (AssemblyAI Universal-3.5 Pro). The original design used local Whisper, then Deepgram —
  the engine is swappable behind the same orchestration shell.
- **The "orchestrator" part is the focused-window injection + command parser + an optional
  handoff review queue** that renders a registry of resolved work for a human to review. The
  queue is read-only — it opens and copies, it never writes a record or picks a destination.
  That review surface, on top of a dictation tool, is what makes it a control surface for a
  whole setup.
- **Continuous streaming costs money** (cloud usage even for ambient audio). A local
  voice-activity-detection pre-filter to gate silent audio is a planned improvement.

## Control window

A small always-on-top window shows the current state (`SLEEPING` / `ARMED`) and last status,
with Arm / Sleep / Quit buttons — so the state machine is visible and recoverable, not
hidden.

## Why this fits a "talk to your whole setup" goal

This tool already does the hard, working part: **always-on wake-word voice → command
recognition → actions in any focused window**. What it doesn't do is *understand your whole
setup* — it drives the currently-focused app, it doesn't hold a model of every system you
have. That "sees and controls everything" layer is the orchestrator on top, and it's the
piece that's still hard / not-yet-there in the general case. The voice surface is the easy,
solved part.

---

*This is the current/live spec. Earlier designs (push-to-talk local-Whisper; Deepgram merge)
are preserved as history but superseded by this wake-word, streaming build.*
