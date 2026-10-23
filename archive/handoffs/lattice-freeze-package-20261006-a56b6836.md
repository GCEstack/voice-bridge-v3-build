# HANDOFF — LATTICE: stale README refreshed (claimed Stage 2 blocked while Stage 2/3/4 proofs existed), 4 open-question decisions delivered for Don, full battery green (243 tests, replay 6/6 NO FAKE PASS, freezes PASS, identity MATCH 59 files); freeze package handed to Enzo for ruling

- handoff id     : lattice-freeze-package-20261006
- source         : lattice (engine identity, not a seat)
- state          : completed
- created        : 2026-10-06T07:10:54-07:00
- recipient      : Enzo
- result artifact: C:\Users\Dekan AI Brother\Desktop\GCE_EC_Math_Engine_Show_Down\LATTICE_FREEZE_PACKAGE_2026-10-06.md

## Result

# LATTICE — FREEZE PACKAGE FOR ENZO (one page + evidence map)

**Engine name:** LATTICE (engine identity, not a seat) · EdgeCrew Math Engine family
**Build:** `CONTENDER_BIG_PICKLE_STAGE1A_REPAIR` · model `zen-free/big-pickle`
**Path:** `…\GCE_EC_Math_Engine_Show_Down\CONTENDER_BIG_PICKLE_STAGE1A_REPAIR\`
**Prepared:** 2026-10-06 · Authority: **Don** (freeze requested) · Ruling: **Enzo** — **PENDING**
**Identity/bootstrap:** `GCE_IDENTITY\LATTICE\AGENTS.md` (router registration still pending a Don roster amendment)
**Sibling precedent:** `DATUM_FREEZE_MANIFEST.md` (same folder, ruled by Enzo 2026-10-05)

**THE ASK:** one ruling — **FREEZE / FREEZE-WITH-CONDITIONS / DO NOT FREEZE** — plus,
if Enzo prefers, a view on the four recommended decisions in §7 (each may also be
deferred; they are parked either way).

> **Nothing in the build was mutated for this package.** This pass refreshed a stale
> `README.md`, added one decision document, and ran the battery. Engine code,
> adapters, tests and all shipped constants are byte-identical to their 2026-10-05
> adopted state — `verify_freezes` confirms 0 unexplained differences.

---

## 1. WHAT IS PROPOSED TO BE FROZEN

The **build as it stands**: 59 files under the criteria below, becoming an
immutable reference authority. Post-freeze, any change is a new derived build
(new version, new proof, new freeze).

Criteria (implemented in `stage4/verify_identity.py`, cannot drift): all
`*.py|json|md|txt|toml|yaml`, excluding `__pycache__`, `.pytest_cache`, `evidence`,
`tmp`, `runs_calibration`, `runs_stage2`, `archived_logs`, `latest_logs`.
Derived panels and published runs are **evidence of record, outside the code
fingerprint** — they are provenance, not shipped bytes.

## 2. FINGERPRINTS (re-verified at package time, FACT)

| artifact | fingerprint | files | status |
|---|---|---|---|
| **LATTICE build (this package)** | `f533a5de847460f23777d639dafb7363de134ac697cac49292bdb2bb787bee32` | **59** | ✓ MATCH |
| Frozen parent `CONTENDER_BIG_PICKLE` | manifest `proof/stage1/stage1_manifest.json` | 36 inventory / 24 hashed | ✓ **PASS 24/24** |
| Falcon proving package `MLB_FULL_SLATE_20261005T164940Z` | manifest `file_count=295`, `frozen_at=2026-10-05T19:37:48.132Z` | 295 | ✓ **PASS 295/295** |

Baseline discipline: a session-start identity check was run **before any edit**
and recorded MATCH at 58 files / `30650fa3fcf12882873c05fff543b29960c39a44f27cd1bff5f4be294f3565f7`.
The 59-file baseline above was taken **after** the two authorised document changes
and re-confirmed MATCH. Old and new values are recorded in
`GCE_IDENTITY\LATTICE\AGENTS.md` §2, which is the single source for the baseline.

## 3. BATTERY OF RECORD — run 2026-10-06, all gates green

```
tests            243 passed in 1223.80s (0:20:23)   0 failures, 0 regressions
                   91 Stage-1 + 67 Stage-1A + 52 Stage-3 + 33 Stage-4
replay battery   6/6 PASS   NO FAKE PASS: True
                   A untouched=REPLAY_EXACT · B changed input=REPLAY_MISMATCH
                   C changed coefficient=REPLAY_MISMATCH (in-process)
                   D tampered output=REPLAY_MISMATCH · E no identity=REPLAY_UNAVAILABLE
                   F determinism=identical
verify_freezes   OVERALL PASS
                   frozen parent PASS 24/24 · Falcon PASS 295/295
                   touch scope PASS: 13 diffs vs Stage-1 parent, 0 unexplained
                   Stage-3 non-regression: 0 unchanged-but-unauthorised,
                   2 authorised adoption edits, both printed with old+new hash
verify_identity  MATCH (59 files, hash above)
```

Run conditions: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` (a global pytest plugin rejects
`--timeout` and hangs the run), Python 3.14.2, no network writes, Falcon package
opened read-only.

## 4. SHIPPED STATE AT FREEZE

**ADOPTED 2026-10-05** (Don's authorisation, holdout-backed, battery-cleared):

| parameter | was | now | evidence |
|---|---|---|---|
| `offense_weight` | 0.5 | **0.91049** | OLS se 0.07249, t +12.6, CI 0.7684..1.0526 |
| `defense_weight` | 0.5 | **0.94288** | se 0.05657, t +16.7, **sign-converted** from fitted −0.94288 (copying the raw negative would have inverted defense) |
| `dispersion_ratio` | 1.16 | **2.1839** | train 2.1740 / valid 2.1702 / holdout 2.1839 / all 2.1773 |

Holdout NegBin NLL **2.456594** vs incumbent **10.959622**; like-for-like 2×2 shows
both effects improve holdout independently. **Caveat carried into the freeze:**
dispersion alone is **~97%** of the gain (0.0908 of 0.0930); the weights move NLL by
0.0022. The weights are correctly estimated, but they are not the important change.

**UNFITTED — unchanged, deliberately:**
`STARTER_SCALE_RUNS_PER_9 = 0.55` · `BULLPEN_SCALE_RUNS_PER_9 = 0.45` ·
`RUNNER_UP_RATE` rungs 4.95/4.74/4.55/4.36/4.15 · `base_rate 4.55` ·
`home_advantage_units 0.28` · `pace_correlation −0.10` · postseason separable and
out of every production fit.

**RETRACTED — must not be re-cited after freeze:**
1. *"The bucket ladder is ~4× too narrow."* Wrong: `term = SCALE × dev × share`, so
   ladder width and scale are the same lever. Declared and measured ladders agree
   within **6%** (0.3646 vs 0.3437 runs at the bucket extreme).
2. *"The pitching slope IS directly comparable to the engine's SCALE."* False:
   wrong dimension, wrong sign, game-state contaminated, unstable out of sample.
3. Stage 3's *"Replay battery 6/6"* was stale — the battery raised `TypeError` on
   line 1 since the Stage-3 signature change. Repaired 2026-10-05, baselined green
   **before** any adoption.

## 5. EVIDENCE MAP (all read-only, all inside the build)

| artifact | path |
|---|---|
| Stage-1A repair proof | `proof\stage1a_repair\STAGE1A_REPAIR_PROOF.md` |
| Stage-2 real-data proving (Falcon package, 2 events) | `proof\stage2\STAGE2_MLB_PROOF.md` |
| Stage-3 Don rulings / methodology | `proof\stage3\STAGE3_RULINGS_PROOF.md` |
| Stage-4 bullpen + calibration (949 lines) | `proof\stage4\STAGE4_BULLPEN_CALIBRATION_PROOF.md` |
| Session handoff record | `proof\stage4\_HANDOFF_READ_ME_FIRST.md` |
| **Decision pack — the 4 open questions** | `proof\stage4\OPEN_QUESTION_DECISIONS_2026-10-06.md` |
| Refreshed README (was the stale artifact) | `README.md` |
| Baseline authority | `GCE_IDENTITY\LATTICE\AGENTS.md` §2 |
| Calibration panels (evidence, outside fingerprint) | `runs_calibration\` — 12,379-game score panel + 95,672-row boxscore panel, 2021–2025 |

## 6. WHAT FREEZE WOULD MEAN (draft operating contract for Enzo's ruling)

> **Run LATTICE as frozen. No mutation of the 59 files. Preserve MISSING ≠ ZERO,
> PROXY ≠ DIRECT, market blindness, replay binding, WHY attribution, and the
> SUPPORTED / DEGRADED / NO READ behaviour. Do not resolve the four parked
> questions inside the frozen build. Do not tune toward a market or toward Don.
> Report UNFITTED rather than publishing a number that cannot be defended on
> held-out data. Any methodology expansion = LATTICE-derived-next: new version,
> new proof, new freeze, explicit Don authorisation.**

- The frozen parent `CONTENDER_BIG_PICKLE` and the Falcon package remain
  read-only and are already frozen by their own manifests; LATTICE never wrote to
  either (`verify_freezes` enforces this).
- `GCE_IDENTITY\LATTICE\AGENTS.md` stays load-control space, never a working
  directory, and `lattice` never appears as a seat `source` except in the declared
  form `lattice (engine identity, not a seat)`.

## 7. FOUR PARKED QUESTIONS — recommendations attached, **none resolved**

| # | question | recommendation on the table | owner | state |
|---|---|---|---|---|
| 1 | Park-factor wiring | Sparse **stability-gated** mechanism (Coors +1.319 · T-Mobile −0.977 · Tropicana −0.851; all other venues **MISSING**, never zero-filled; naive ratio index forbidden) — but **park it in this freeze** and open it as LATTICE-derived-next, because it invalidates every replay hash | **Don** | **PARKED / OPEN** |
| 2 | ERA vs RA9 semantics | **Declare the scale = ERA** (base_rate 4.55 reconciles with pooled ERA9 4.5308, not RA9 4.9370); correct labels only — no number moves | **Don** (semantics) | **PARKED / OPEN** |
| 3 | Home advantage | **Authorise the D1 design** (paired within-venue contrast, prior-only team controls, 3-split sign stability, holdout-NLL gate); hold `home_advantage_units = 0.28` declared meanwhile. **No new number is proposed** — FE +0.044 is a cross-check that came back small, not a candidate | Don authorises · LATTICE designs | **PARKED / OPEN** |
| 4 | Starter mechanism | **Hold 0.55 UNFITTED**; approve the Falcon request to complete 2024 boxscores (~58% → 100%, ≈ +5,000 usable rows, shard-then-merge); re-open only when CI can separate 0.22 from ~0.35 on holdout | Don dispatches · Falcon acquires · LATTICE re-fits | **PARKED / BLOCKED ON FALCON** |

Full evidence and the cost of each option:
`proof\stage4\OPEN_QUESTION_DECISIONS_2026-10-06.md`.

## 8. HONEST CAVEATS CARRIED INTO THE FREEZE

1. **Price-level trust is NOT READY.** The engine expected 9.01 runs against a
   nine-book unanimous 6.5 on 849834; starter + bullpen close ~0.3 of a 2.7-run gap.
   The **+79% / +41% EV figures at the offered line are distribution artefacts, not
   edges, and must not be presented as tradeable.** Freezing does not fix this and
   must not be read as endorsing it.
2. **The confidence band is not empirically calibrated** — the Stage-4 panels
   calibrate parameters, not the band.
3. **Dispersion is ~97% of the adopted gain** (see §4). Anyone reading "we adopted
   fitted weights" without that caveat has been told the wrong story.
4. **The identity is not router-registered** (bootstrap §8): `load lattice
   bootstrap` stays unavailable until Don amends the frozen roster. That is a
   roster act for Don/Enzo, not a defect in the build.
5. **`_HANDOFF_READ_ME_FIRST.md` §0 says "Stage 4 proof NOT YET WRITTEN"** — that
   line is stale (the proof exists and is listed in §5). It is a session-resume
   note kept for provenance; the authoritative status is the refreshed `README.md`
   and this package.

---

**Package complete. Freeze second — the work was finished first, then the battery
was run on the finished state.**
Prepared by `lattice (engine identity, not a seat)` · builder occupant model
declared at session start (MODEL != SEAT) · for ruling by **Enzo**, authority **Don**.

## Lineage

This payload was produced from VoiceBridge queue item `lattice-freeze-package-20261006`, which is archived automatically on successful handoff creation. Original result: C:\Users\Dekan AI Brother\Desktop\GCE_EC_Math_Engine_Show_Down\LATTICE_FREEZE_PACKAGE_2026-10-06.md
