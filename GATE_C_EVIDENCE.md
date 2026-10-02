# GATE C — EVIDENCE

**Build:** VoiceBridge V3 integrated build v0.1.0
**Tree:** `C:\Users\Dekan AI Brother\GCE_DON\voice-bridge-v3-build\`
**HANDOFF_ID:** 20261001_NICO_V3_BUILD_ORDER_001
**Date:** 2026-10-01
**Precondition:** Gate P green (`GATE_P_EVIDENCE.md`) — this gate ran after it, never before.
**Verdict:** **GATE C GREEN** — all four stated criteria met, with the same
three runtime limitations carried forward from Gate P §5.

---

## Criteria as stated

> "G6 byte-identity regression passes on the integrated build · durable
> full-fidelity transcripts on disk · interpretation shadow running offline
> alongside · health observable"

| # | Criterion | Verdict |
|---|---|---|
| C1 | G6 byte-identity regression passes on the integrated build | **GREEN** |
| C2 | Durable full-fidelity transcripts on disk | **GREEN** |
| C3 | Interpretation shadow running offline alongside | **GREEN** |
| C4 | Health observable | **GREEN** |

`pytest tests -q` → **172 passed, 0 failed** (32 of them the Gate P harness,
17 the Gate C harness, 2 the carried-over G6 suite, 121 the unchanged baseline
suite). Was 170 before the 2026-10-01 wake-word amendment — see
`GATE_P_EVIDENCE.md` §0. That fix is on the STT/dictation path and touches
nothing in C1–C4; the G6 suite is unchanged and still passes.

---

## C1 — G6 byte-identity regression passes on the integrated build

The carried-over G6 suite proves the persistence *component*. That is necessary
and it is **not sufficient**: a component can be byte-perfect while the
integrated pipeline truncates on the way to it. Every C1 check below therefore
also runs through the live pipeline, not only against the component in a vacuum.

| Check | Test | Evidence |
|---|---|---|
| The G6 suite is the salvage suite, unmodified | `test_c1_g6_suite_is_the_salvage_suite` | `tests/test_g6_regression.py` is **byte-identical** (SHA-256) to `voice-bridge-v3\tests\`. A rewritten test proves nothing. |
| The salvage suite passes standalone on this build | `python tests/test_g6_regression.py` | `[PASS] G6 regression test: 619 chars persisted byte-identical` · `[PASS] UI preview may shorten (80 chars)` · `[PASS] Durable source preserved (592 chars)` · `ALL G6 TESTS PASSED` |
| Byte-identity through the **live pipeline** | `test_c1_g6_byte_identity_through_the_live_pipeline` | The suite's own 619-char fixture pushed through recv → engine → dispatcher. Disk file contains `G6_TEXT.encode("utf-8")` as raw bytes; `is_partial` false; `event_id` matches the filename stem |
| Byte-identity for non-ASCII text | `test_c1_g6_unicode_round_trips_byte_exactly` | A 537-char fixture with em/en dashes, ellipsis, guillemets, `Café naïve`, `Ω π`, 日本語, テスト, ✅, 👩‍💻, a code fence, a tab and trailing spaces. Round-trips exactly, and the file stores the **characters** — `\u2014`, `\u65e5` etc. are asserted absent, so `ensure_ascii=False` cannot be quietly flipped (it would still round-trip through `json.load`, which is why the escapes are checked directly) |
| The write happens **before** the typing | `test_c1_persist_precedes_typing` | The write and the type call are instrumented and the *sequence* is asserted. Typing is a transform, so a character on screen with no file behind it is a G6 violation even when both halves "worked" |

**The ordering is structural, not a convention.** The engine loop
(`_engine_loop`) performs the durable write and only then enqueues onto
`_final_queue` for typing. There is no code path that types a final without its
transcript already on disk.

---

## C2 — durable full-fidelity transcripts on disk

| Check | Test | Evidence |
|---|---|---|
| One record per utterance | `test_c2_durable_corpus_has_one_record_per_utterance` | 3 utterances × (1 partial + 1 final) → exactly 3 files, contents match, event ids distinct |
| A record is evidence, so it carries provenance | `test_c2_durable_records_carry_provenance` | `event_id`, `timestamp`, `raw_text`, `audio_path`, `duration_seconds`, `stt_provider`, `stt_model`, `is_partial` all present |
| Partials never reach disk | `test_c2_no_partial_ever_reaches_disk` | 25 partials → 0 files, `durable_writes=0`, `ephemeral_partials_not_written=25` |
| Two independent sinks, one text | `test_c2_audit_log_agrees_with_the_durable_record` | The durable transcript is read back from disk, written to `intent_audit.log`, and the **whole string** is asserted present with no `[TRUNCATED FOR PREVIEW]` marker. Written by different code on different threads; if they could disagree, one would be decoration |
| Durability is atomic | `test_surgery_c_exactly_one_durable_per_utterance` | Write to `.json.tmp` then `os.replace`. A crash mid-write cannot leave a half-written file that reads as complete. No `.tmp` residue after a run |

**Where they land:** `data/transcripts/<event_id>.json` (config
`paths.transcripts`). **Durability accounting** is exposed via
`CaptureService.durability_report()` → `{durable_writes, ephemeral_partials_not_written,
durable_files_on_disk, last_error}` — so the contract is observable at runtime
and not only in a test.

**The candidate ships an empty corpus.** The `data/` directory created by my
verification runs was removed before hand-off, so Don's first real-usage run
starts clean and every file he sees is his own.

---

## C3 — interpretation shadow running offline alongside

| Check | Test | Evidence |
|---|---|---|
| Runs alongside, and never blocks dictation | `test_c3_shadow_runs_alongside_without_blocking_capture` | The shadow thread consumes a real durable record and writes its artefact; the utterance is typed in the same window. The shadow has its own queue and its own thread — a slow shadow becomes slow *shadow*, never lost dictation |
| It has no authority over live dictation | `test_c3_shadow_has_no_authority_over_live_dictation` | `"stop listening right now please"` is **typed verbatim** and does **not** pause the bridge — the baseline behaviour (Don 2026-09-25) is preserved against the shadow's own classification of the same words |
| It writes to its own directory and nowhere else | `test_c3_shadow_writes_only_to_its_own_directory` | `shadow_log_dir != transcripts_dir`; the transcript corpus still holds exactly 1 file; no shadow artefact leaked into it (`"claims" not in payload`) |
| **Scope lock: Stage 2 only** | `test_scope_lock_no_stage3_authority` | Asserted on the shipped source: no `emit_claim`, `resolve_reference`, `apply_policy`, `stage3`, `publish` surface. One output directory: `shadow_log_dir` |
| The Stage 2 files are the salvage files | `test_shadow_and_g6_suite_shipped_byte_identical` | `interpretation_shadow.py` and `test_g6_regression.py` are **byte-identical** (SHA-256) to the salvage |
| Standalone offline run | `python -m src.interpretation_shadow data\transcripts data\shadow-log` | `Interpretation complete: 4 transcripts processed` — runs over an existing corpus with no capture running, which is what "offline" has to mean |

Output: `data/shadow-log/<event_id>.json`, one file per finished utterance, with
`claims[]` carrying `speech_act`, `slots`, `confidence` and `model_version` on
every claim. Partials are deliberately **not** shadowed — a partial has no
stable meaning, and shadowing a moving target is noise.

---

## C4 — health observable

| Check | Test | Evidence |
|---|---|---|
| A queryable property, not a string in a widget | `test_c4_health_is_reachable_without_the_gui` | `bridge.v3_health()` → `(bool, str)`; engine `is_running()` / `is_healthy()` agree |
| Silence is a fault, not a healthy quiet | `test_c4_engine_reports_silence_as_a_fault` | Threshold 1 s: healthy, then FAULT with `"silence fault … threshold=1"`, then healthy again on `record_audio()`. Silence clears by itself because the VAD gate makes silence the normal idle state |
| The audio path's verdict reaches the engine | `test_c4_external_fault_is_latched_and_reported` | `recv loop dead` latched. A healthy tick does **not** clear it. Only an explicit `clear_fault()` does |
| A fault survives a failed recovery | `test_flow_websocket_reconnect_on_drop` | Real supervisor thread, rebuild raises → fault still latched, cause preserved (`websocket not connected`, not the generic `no capture`) |
| A successful recovery clears it | `test_successful_reconnect_clears_the_health_fault` | Without this, "the fault is latched" is half a contract — a fault that can never clear is indistinguishable from a broken indicator |
| A missing engine reports FAULT | `test_c4_health_survives_a_missing_engine` | `"not initialised"` — never silence |
| The engine thread cannot die unnoticed | `src/voice_bridge.py::_ensure_engine_thread` | `_engine_loop` is the sole consumer of `_turn_queue` and the only thing between a spoken utterance and a durable transcript. If it died, finals would pile up and nothing would be typed or written — total and silent. The supervisor restarts it and logs the restart |

**Surfaced in the UI, minimally** (STEP 3.D): one added `health_label` directly
under the existing status line, reading `HEALTH ok · stt … · capture …` in green
or `HEALTH FAULT · <cause>` in red. Nothing else in the panel layout moved. The
line is refreshed on every supervisor tick.

The point of putting it in the window and not only the log file: the log file is
exactly what nobody was reading when the baseline's Tier-3 watcher died silently
for four days.

---

## Also verified at Gate C — one audio path, not two

`test_capture_audio_path_is_not_duplicated` asserts `capture_service.py`
contains no `websockets`, no `RawInputStream` and no `sounddevice`, and that
`src/capture.py` is byte-identical to the frozen baseline.

This is the rejection recorded in `GATE_P_EVIDENCE.md` §3 and in the
`capture_service.py` docstring, re-asserted here as an executable check: a
second WebSocket loop would mean a second billed session.

---

## Runtime limitations — carried forward unchanged from Gate P §5

Not verified, not counted green, and none of them resolvable without Don's
real-usage run:

1. **No live AssemblyAI session.** No key is present in this tree by design.
   Everything downstream of the STT boundary is verified; the boundary is not.
2. **No real microphone.** VAD logic verified against real audio-shaped PCM; no
   PortAudio device was opened.
3. **No rendered Tk window.** Widget construction and handler wiring are
   asserted; nobody has looked at it. The MODE line and the new health line are
   the two things worth a human glance.
4. **No real network drop.** Reconnect is verified against a capture reporting
   itself dead; backoff timing under a genuine drop is unmeasured.

## One item Don must supply before the run

`.env` with `ASSEMBLYAI_API_KEY` in `voice-bridge-v3-build\`. It is not bundled,
was not copied from the live tree, and appears nowhere in this build, its logs
or its tests. The key is referenced by location only. The engine refuses to
start without one and says so:

```
[CONFIG ERROR] config error: STT API key missing
```
