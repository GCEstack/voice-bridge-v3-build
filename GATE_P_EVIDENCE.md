# GATE P — EVIDENCE

**Build:** VoiceBridge V3 integrated build v0.1.0
**Tree:** `C:\Users\Dekan AI Brother\GCE_DON\voice-bridge-v3-build\`
**HANDOFF_ID:** 20261001_NICO_V3_BUILD_ORDER_001
**Date:** 2026-10-01
**Verdict:** **GATE P GREEN** — with three items explicitly NOT verifiable without
Don's real-usage run. They are listed in §3 and are not counted green.

---

## 0. AMENDMENT — 2026-10-01, post-acceptance, found on a re-probe

**Sec. 2 flow #1 (wake word → activate listening) was NOT green when this
document was first issued. It is green now. The original claim was wrong and is
corrected here rather than quietly overwritten.**

What happened: the flow was verified against the SLEEPING/ARMED branch with
`continuous=False`. That branch is **unreachable in the live build** — `run()`
force-sets `self.continuous = True`, which returns before the wake-word logic is
ever reached. In the live path, saying *"hey keel"* **typed the words "hey keel"
into whatever window was focused and armed nothing.** Probed and confirmed
before the fix:

```
live continuous value : True
state before          : sleeping
typed                 : ['hey keel this is the first full sentence of the passage ']
state after wake word : sleeping     <-- never armed
```

A verified-but-dead code path is not verification. This is exactly the ground-vs-spec
conflict this seat is required to surface before signoff, and it was missed on
the first pass. The Sec. 2 inventory lists the flow as required, so a live path
that bypasses it is a parity failure, not a legacy quirk.

The fix is minimal and touches no other flow: a leading wake word is consumed
(arms; bare word types nothing, word+payload types the payload), and an
utterance that does not start with a wake word is completely untouched.
`_find_wake_word` is now word-boundary aware, so "keelbase" and "keelson" are
not mangled — the pre-existing `startswith` would have eaten them.

| | Before | After |
|---|---|---|
| `hey keel` | typed as `hey keel ` | arms, types nothing |
| `hey keel <text>` | typed in full | arms, types `<text>` |
| `<text>` | typed | typed (unchanged) |
| `keelbase …` | typed | typed (unchanged, and now protected) |

Test count 170 → **172**; the two new tests are the live-path behaviour and the
word-boundary guard. Self-test still 26/26, G6 suite unchanged and passing.
No other evidence in this document was affected.

**This finding post-dates Serafina's acceptance ruling**, which reviewed the
170-test evidence. It is disclosed rather than folded in silently.

---

## 1. How to reproduce every number in this file

```
cd C:\Users\Dekan AI Brother\GCE_DON\voice-bridge-v3-build
"C:\Users\Dekan AI Brother\GCE_DON\voice-bridge\.venv\Scripts\python.exe" -m pytest tests -q
"C:\Users\Dekan AI Brother\GCE_DON\voice-bridge\.venv\Scripts\python.exe" -m src.voice_bridge --self-test
```

| Run | Result |
|---|---|
| `pytest tests -q` | **172 passed**, 0 failed, 2 warnings (both in the carried-over G6 suite: its functions `return True`, a pre-existing salvage quirk, unmodified) |
| `python -m src.voice_bridge --self-test` | **26/26 checks passed → OK** |
| `python tests/test_g6_regression.py` | **ALL G6 TESTS PASSED** (619-char + 592-char fixtures byte-identical) |

Two verification methods, used deliberately and not interchangeably:

- **BEHAVIOUR** — the real object is exercised and the effect observed.
- **BYTE-STABLE** — SHA-256 against the frozen baseline
  `voice-bridge-baseline-20260930\`, which must be identical. Used wherever the
  Sec. 2 requirement *is* "preserved unchanged", because a behavioural test
  passes just as happily after a change nobody asked for.

---

## 2. CONTROLS — Sec. 2 inventory

| # | Control | Test | Method | Result |
|---|---|---|---|---|
| 1 | Mic toggle | `test_control_mic_toggle` | BEHAVIOUR — real handler, real status strings, fake capture; also proves it degrades with no capture rather than raising | **VERIFIED** |
| 2 | Listening indicator | `test_control_listening_indicator` | BEHAVIOUR — asserts the strings the running code emits on unmute and on pause, so the indicator cannot read "live" while paused | **VERIFIED** |
| 3 | MODE display | `test_control_mode_display` | INSPECTION on the Tk label literal + BEHAVIOUR on the driving flag; `run()` forces `continuous=True` so the label cannot lie | **VERIFIED** (label not rendered — no display) |
| 4 | Reconnect | `test_control_reconnect` | BEHAVIOUR — capture stopped, cleared, backoff reset 99.0 → 2.0 | **VERIFIED** |
| 5 | Quit | `test_control_quit` | BEHAVIOUR — voice `quit` schedules close; `_on_close` stops capture and sets `_stopping` | **VERIFIED** |
| 6 | Show dismissed checkbox | `test_control_show_dismissed_checkbox` | BEHAVIOUR on the filter (`visible()`), INSPECTION on the `ttk.Checkbutton` construction. A missing control is a missing binding. | **VERIFIED** |
| 7 | Refresh | `test_control_refresh_and_status_line` | INSPECTION on the button→`refresh` binding, BEHAVIOUR on `scan_registry` | **VERIFIED** |
| 8 | Status line (queue state + registry path) | `test_control_refresh_and_status_line` | INSPECTION on the rendered string; both the count and `Registry: {path}` are asserted present | **VERIFIED** (not rendered) |
| 9 | Row actions ×6 | `test_control_row_actions`, `test_row_dismiss_is_local_state_only` | INSPECTION on all six buttons/handlers, BEHAVIOUR on `record_text()` payload and on the Dismiss round trip | **VERIFIED** |

**Controls: 9/9 verified, 3 of them on the Tk construction rather than a drawn
window.** `test_queue_panel.py` (13 baseline tests) also passes unchanged.

---

## 3. FLOWS — Sec. 2 inventory

| # | Flow | Test | Method | Result |
|---|---|---|---|---|
| 1 | Wake word → activate listening | `test_flow_wake_word_in_the_live_continuous_path`, `test_wake_word_match_is_word_boundary_aware`, `test_flow_wake_word_to_listening_legacy_branch` | BEHAVIOUR — all four wake words, longest-match wins, **in the `continuous=True` path `run()` actually leaves**; bare wake word arms and types nothing; wake word + payload strips the wake word; no wake word is untouched; word-boundary guard | **VERIFIED (AMENDED — see §0)** |
| 2 | VAD silence gating | `test_flow_vad_gate` | BEHAVIOUR — real `_gate_should_send`, quiet closes, loud opens, manual mute wins. `test_vad_gate.py` (6 baseline tests) also passes unchanged. | **VERIFIED** (no PortAudio device opened) |
| 3 | Continuous capture → STT → dictation, **COMPLETE text** | `test_flow_full_text_reaches_dictation_and_disk` | BEHAVIOUR — a 501-char utterance pushed through the real pipeline (recv → engine → dispatcher). Asserted complete at the typing buffer **and** byte-identical on disk. | **VERIFIED** (no live AssemblyAI session — see §5) |
| 4 | Queue panel auto-refresh from `queue\` | `test_flow_queue_panel_auto_refresh_reads_registry` | BEHAVIOUR — scans the configured registry, asserts online, asserts the missing-registry case is offline and **never auto-created** | **VERIFIED** |
| 5 | WebSocket reconnect on drop | `test_flow_websocket_reconnect_on_drop`, `test_successful_reconnect_clears_the_health_fault` | BEHAVIOUR — the real supervisor thread driven against a capture reporting `websocket not connected`; asserts the dead capture is stopped, a rebuild is attempted, the fault is latched through a **failed** recovery, and cleared by a **successful** one | **VERIFIED** (against a simulated drop, not a real socket) |
| 6 | Voice command handlers | `test_flow_voice_command_handlers` | BEHAVIOUR — parsing plus live routing to `execute_command` vs typing. `test_voice_commands.py` (33 baseline tests) passes unchanged. | **VERIFIED** |
| 7 | Keyboard input simulation | `test_flow_keyboard_input_simulation` | BYTE-STABLE + BEHAVIOUR — `keyboard_input.py` is byte-identical to the baseline; dictation really routes through `type_text` | **VERIFIED** |
| 8 | Screenshot capture | `test_flow_screenshot_capture` | BYTE-STABLE — `screenshot.py` identical; public surface present. `test_voice_commands.py` screenshot parse + execute tests pass unchanged. | **VERIFIED** (no real screen capture performed) |
| 9 | Voice profiles | `test_flow_voice_profiles` | BYTE-STABLE + BEHAVIOUR — `voice_profile.py` identical; a profile phrase produces typed output rather than dictation | **VERIFIED** |
| 10 | Config read | `test_flow_config_json_read` | BEHAVIOUR — real loader, including the merged V3 keys, and the assertion that `assemblyai_api_key` is `""` in config | **VERIFIED** |
| 11 | **llm.py behaviour preserved unchanged** | `test_flow_llm_unchanged` | **BYTE-STABLE** — `src/llm.py` and `tests/test_llm.py` are byte-identical to the frozen baseline. `test_llm.py` (5 tests) passes. | **VERIFIED** |

---

## 4. SURGERY POINTS

| Point | Requirement | Test | Result |
|---|---|---|---|
| **A** STT path | Full-fidelity transcript feeds the dictation/cue buffer; Copy Text copies COMPLETE text; `intent_audit.log` keeps writing, now lossless; change documented in code + report | `test_flow_full_text_reaches_dictation_and_disk`, `test_surgery_a_intent_audit_writes_full_text` | **GREEN** — the `text[:80]` bound is gone from the format string; an opt-in `preview_chars` exists but defaults to 0 (never shortens) and a shortened preview is labelled `[TRUNCATED FOR PREVIEW]` in the line itself |
| **B** Queue panel | Read path UNCHANGED; no honesty work | `test_surgery_b_queue_panel_read_path_unchanged` | **GREEN** — `src/queue_panel.py` is **byte-identical** (SHA-256) to the frozen baseline. `config.json`'s `handoff_queue` block is also unchanged, so it still reads the same registry at the same path |
| **C** Partials | Ephemeral partials; exactly ONE final durable transcript per utterance | `test_surgery_c_exactly_one_durable_per_utterance`, `test_c2_no_partial_ever_reaches_disk`, `test_c2_durable_corpus_has_one_record_per_utterance` | **GREEN** — 6 partials + 1 final → exactly 1 file, `durable_writes=1`, `ephemeral_partials_not_written=6`, no `.tmp` residue (write-then-`os.replace`) |
| **D** Health | Engine health (STT connection, capture loop) surfaced into the existing status-line area; observable silence is a fault, never quiet; minimal UI change, layout unchanged | `test_surgery_d_health_is_observable`, `test_c4_*` (4 tests) | **GREEN** — one added `health_label` under the existing status line; nothing else in the layout moved. Silence > threshold = FAULT. A latched connection fault does not self-clear and survives a failed recovery |

**Failure-path guarantees, also asserted** (not in Sec. 2, but they are the
whole reason the baseline was replaced):

- `test_engine_never_blocks_dictation` — a dead engine still delivers the words, and reports FAULT.
- `test_persist_failure_does_not_silence_the_operator` — a failed durable write still delivers the words **and** puts the error on the status line. Both, not one.

---

## 5. NOT VERIFIED IN THIS BUILD — requires Don's real-usage run

These are not counted green. They cannot be produced headlessly and I am not
going to imply otherwise.

1. **A live AssemblyAI v3 WebSocket session.** No API key exists in this tree
   by design (`.env` is not bundled; Don supplies it at run time). STT
   transcription accuracy, real Turn framing, and real `end_of_turn`/
   `turn_is_formatted` behaviour are unexercised. Everything downstream of the
   STT boundary is verified; the boundary itself is not.
2. **A real microphone / PortAudio stream.** The VAD gate logic is verified
   against real audio-shaped PCM; no device was opened. A device that delivers
   silence forever is exactly the case the V3 health line exists to surface —
   and that is only demonstrable on real hardware.
3. **A rendered Tk window.** Widgets, bindings and label strings are asserted
   from source and from the handlers they call. Nobody has looked at the
   window. Item 3 above (MODE display) and the new health line are the two
   things worth a human glance.
4. **A real network drop.** Reconnect is verified against a capture that
   reports itself dead. Backoff timing under a genuine drop is unmeasured.

---

## 6. PARITY DISCIPLINE — the surgery surface is exactly 5 files

`test_surgery_surface_is_exactly_the_declared_files` walks every file in the
frozen baseline and asserts the changed set is **exactly**:

| File | Why it differs |
|---|---|
| `src/intent.py` | Surgery point A — 80-char truncation removed |
| `src/voice_bridge.py` | Surgery points A/C/D wiring + the health line + `mute_btn` init |
| `tests/test_voice_bridge.py` | One test re-pointed at the new queue boundary (claim preserved, mechanism changed) — see §7 |
| `config.json` | V3 engine keys merged in |
| `START-VOICEBRIDGE.cmd` | Interpreter resolution so the candidate runs at all |

Byte-identical to the baseline, among others: **`src/capture.py`**,
`src/queue_panel.py`, `src/llm.py`, `src/config.py`, `src/voice_commands.py`,
`src/voice_profile.py`, `src/keyboard_input.py`, `src/screenshot.py`, and all
10 unchanged baseline test files.

The test **fails** if a future change touches a sixth source file, and
**fails** if a baseline file goes missing. Unrequested changes have to be
argued for, not slipped in.

---

## 7. The one baseline test I changed, and why that is not cheating

`tests/test_voice_bridge.py::test_intent_logged_on_dispatcher_thread_not_recv`
asserted that `on_transcript` puts straight onto `_final_queue`. V3 moved the
boundary one stage earlier: `on_transcript` now hands the frame to `_turn_queue`
(engine/persistence) and the engine writes the durable transcript *before* the
text reaches the typing queue.

The test's actual claim — **the AssemblyAI recv thread must not do disk work** —
is unchanged, and V3 enforces it at a stronger point. So the assertions were
re-pointed at the new boundary and extended (a partial must not reach the
typing queue), not deleted or weakened. Nothing was made to pass by removing a
check.

---

## 8. What the Gate P run changed about the build

Two real defects were found by the harness while it was being written, and both
are fixed:

1. **`mute_btn` was only created inside `_build_ui()`.** Any path reaching
   `_sync_mute_button()` before the window existed raised `AttributeError`.
   Latent in the real app (the UI is always built first) but it is now
   initialised in `__init__`, so a partial UI build or a failed Tk init
   degrades instead of crashing.
2. **The health fault latch was last-write-wins.** The supervisor reports
   `no capture` on every tick after a failure, which overwrote the real root
   cause (`websocket not connected`) one second later. The first reason now
   holds until an explicit clear, so the cause survives.

Neither was on the Sec. 2 list. Both are in the surgery surface and neither
touches a frozen behaviour.

3. **The wake-word gate was dead code in the live build** (found 2026-10-01 on
   a post-acceptance re-probe, fixed — see §0). This one WAS on the Sec. 2
   list, and the first Gate P pass missed it by verifying the dormant branch
   instead of the path that runs.
