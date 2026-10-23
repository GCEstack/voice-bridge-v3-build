# HANDOFF — VoiceBridge / session-queue plumbing reset, Pass 2 implementation

- handoff id     : 20261004-NICO-VB-QUEUE-RESET-PASS2
- source         : Nico (Space Bunny)
- state          : completed
- created        : 2026-10-04
- recipient      : Don
- result artifact: this file
- project        : FRAMEWORK

## OUTCOME

The target flow is built and proven end-to-end in the real target environment.

    MODEL COMPLETES MEANINGFUL WORK
      -> ONE completion artifact
      -> ONE ingest
      -> ONE live queue item in the VoiceBridge session queue
      -> Don: ARCHIVE  (item leaves active queue, preserved in archive)
         or HANDOFF (usable payload produced, then item auto-archived)

The legacy session-ledger / routing / handoff machinery has been removed from
the live path and archived with a hashed manifest. Provenance is preserved.
Nothing in the archive is a runtime dependency.

DONE CONDITIONS: **MET.** Proof below, 30/30 acceptance checks plus live
product and legacy-isolation tests.

---

## FINAL LIVE FLOW

    a model writes a completion artifact (6 required fields)
        |
        v
    python -m src.completion submit <artifact.json>
        |  validate -> dedup (id + content key + archive ledger) -> atomic write
        |  exactly ONE item lands in  <product>/queue/
        v
    VoiceBridge queue panel  (reads <product>/queue/ only, 30s refresh)
        |
        +-- Don presses ARCHIVE  -> moves to archive/items/, event into
        |                           state/archive_ledger.json, item gone
        +-- Don presses HANDOFF  -> writes + VERIFIES archive/handoffs/<id>.md
                                    + sidecar, THEN archives the source
        |
        v
    source item archived. History preserved. Nothing resurrected on restart.

There is **no timer** that can clear actionable work. Membership is location
(`queue/` = active, `archive/items/` = archived), not a field, so no state
value and no age rule can hide work.

---

## FINAL LIVE FOLDER STRUCTURE

    GCE_DON\voice-bridge-v3-build\          <- THE ONE PRODUCT TREE
    |
    +-- src\
    |     +-- completion\                   <- NEW: the whole new path
    |     |     contract.py    completion artifact schema + validation
    |     |     store.py       queue read/write, ARCHIVE, HANDOFF, ledger
    |     |     paths.py       queue root, resolved inside the product tree
    |     |     cli.py         submit / list / show / archive / handoff / stats
    |     |     __main__.py    python -m src.completion
    |     +-- queue_panel.py                 <- REBUILT on the live store
    |     +-- voice_bridge.py  capture, STT, dispatcher (unchanged)
    |     +-- voice_commands.py  03_HANDOFFS voice path DISCONNECTED
    |     +-- capture.py / capture_service.py / intent.py / stt / tts ...
    |
    +-- queue\                ACTIVE items, one JSON per completed work
    +-- archive\
    |     +-- items\          ARCHIVED items (source of record)
    |     +-- handoffs\       HANDOFF payloads (.md) + sidecars (.json)
    +-- state\
    |     +-- archive_ledger.json   durable record of every archive event
    +-- logs\
    |     +-- ingest.log      append-only ingest/action audit
    +-- config.json           `queue` block; NO absolute paths
    +-- .venv\                OWNED runtime (borrow cascade removed)
    +-- .env                  OWNED credential (gitignored, never printed)
    +-- tests\
    |     +-- test_queue_acceptance.py   30/30
    |     +-- fixtures\                  controlled completion artifacts
    +-- START-VOICEBRIDGE.cmd           the ONE launcher, no queue plumbing

    GCE_DON\voice-bridge\    retained ONLY: .venv, .env, .git, config.json,
                             logs, docs, requirements. Source/tests/queue
                             archived. No longer a runtime dependency.

    GCE_DON\command-center\  DevPad + Cable Car + ai-inbox + inbox-mcp.
                             routing\registry.js retained (MODEL != SEAT).

---

## COMPLETION ARTIFACT CONTRACT

```json
{
  "id":         "<stable-id-for-this-work>",     required
  "created_at": "<ISO-8601>",                    required
  "source":     "<seat>",                        required
  "subject":    "<one line: what happened>",     required
  "artifact":   "<path to the result>",           required
  "state":      "completed|partial|failed|blocked", required
  "project":    "<optional>",                    optional
  "workstream": "<optional>"                     optional
}
```

Deliberately absent: `from`, `to`, `route_type`, `routing_status`, `gate`,
`next_route`, `drive_file_id`, mandatory project/workstream, seat lifecycle
states, legacy handoff header shapes.

- Optional metadata is never required and never suppresses visibility.
- `state` describes THE WORK. Queue membership is location, never a field.
- The artifact is fully understandable with no routing machinery present.

---

## ARCHIVE BEHAVIOR

- Initiated ONLY by Don's ARCHIVE button or the CLI. Nothing else, ever.
- Removes the item from the active queue; preserves the item record in
  `archive/items/` and writes an event to `state/archive_ledger.json`.
- The source result file is never touched or deleted.
- Survives restart: membership is a filesystem fact, not memory.
- **The legacy silent age rule is removed.** It previously archived anything
  older than ~24h every 30 seconds with no human action. That guarantee that
  actionable work vanishes on a timer no longer exists anywhere in the code.
- Archived work cannot be re-queued: the ledger's content-key index makes
  re-submission a reported duplicate, not a resurrection.

## HANDOFF BEHAVIOR

`QUEUE RESULT -> USABLE HANDOFF COPY -> ARCHIVE SOURCE`

Order is enforced, not incidental:

1. read the result body from the artifact path
2. write the payload (`archive/handoffs/<id>.md`) + machine sidecar (`.json`)
3. **verify** the payload exists and is non-empty
4. only then auto-archive the source

Any failure in steps 1-3 returns a visible error, leaves the source ACTIVE and
archives nothing. No false archive is possible. Proven by test.

Payload carries: subject, source, state, created, recipient, result path,
project/workstream when present, the full result body, and lineage back to the
originating queue item.

Recipient is free text and optional. No receiving-seat taxonomy, no mandatory
dispatch, no routing engine.

---

## FILES CREATED

    src\completion\contract.py
    src\completion\store.py
    src\completion\paths.py
    src\completion\cli.py
    src\completion\__main__.py
    src\completion\__init__.py
    tests\test_queue_acceptance.py
    tests\fixtures\TEST_A_artifact.json + TEST_A_result.md
    tests\fixtures\TEST_C_artifact.json + TEST_C_result.md
    tests\fixtures\TEST_D_artifact.json + TEST_D_result.md
    tests\fixtures\TEST_E_artifact.json + TEST_E_result.md
    tests\fixtures\TEST_A_dupcheck.json
    tools\repoint_config.py
    queue\                            (runtime, created empty)
    archive\items\  archive\handoffs\ (runtime, created empty)
    state\archive_ledger.json
    logs\ingest.log
    .venv\                            (Python 3.14.2, all requirements installed)
    .env                              (copied from the frozen tree; value never printed)

## FILES CHANGED

    src\queue_panel.py            REBUILT on the live store. Age auto-archive
                                  deleted. Legacy 7-column schema replaced by
                                  the minimal 5. ARCHIVE + HANDOFF added.
                                  Dismissed-state concept removed.
    src\voice_commands.py         HANDOFF_LAUNCHER + _start_handoff() severed.
                                  Saying "handoff" now reports the retirement.
    config.json                   handoff_queue / queue_refresh / queue_filters
                                  blocks replaced by one `queue` block with no
                                  absolute paths.
    START-VOICEBRIDGE.cmd         projection block deleted; borrow cascade
                                  removed; requires local .venv and .env.
    package.json (command-center) handoff-queue* scripts removed; npm test
                                  no longer references the deleted producer test.
    routing\state.js              STATE_PATH default repointed to
                                  command-center\data\routing_state.retired.json
                                  so retired routing state cannot be recreated
                                  under the governance root.
    cable-car\transport\localDelivery.js
                                  _projectToQueue() call removed and method
                                  retired to a no-op event. Cable Car transport
                                  itself untouched.
    GCE_SEAT_ROUTER.md            V2 machine footer spec replaced with the
                                  completion-artifact return contract.
    GCE_IDENTITY\Chiave\AGENTS.md          routing footer retired
    GCE_IDENTITY\Coda\AGENTS.md            routing footer retired
    GCE_IDENTITY\Enzo\AGENTS.md            routing footer retired
    GCE_IDENTITY\Serafina\AGENTS.md        routing footer retired
    GCE_IDENTITY\Vittorio\AGENTS.md        routing footer retired
    GCE_IDENTITY\Magpie\SESSION_HEADER.md  06_HANDOFFS path repointed
    GCE_IDENTITY\Pigeon\SESSION_HEADER.md  06_HANDOFFS path repointed
    GCE_IDENTITY\Nico\PROJECTS\EDGECREW_QUANT\AGENTS.md      06_HANDOFFS repointed
    GCE_IDENTITY\Corrado\PROJECTS\EDGECREW_QUANT\AGENTS.md   06_HANDOFFS repointed
    GCE_IDENTITY\Coda\BOOTSTRAP_ROOKIE.md   GCE_ROUTING_STATE default repointed

## FILES DISCONNECTED (edited to sever a live reference; not deleted)

    cable-car\transport\localDelivery.js  -> _projectToQueue no longer projects
    src\voice_commands.py                 -> 03_HANDOFFS no longer launchable
    command-center\routing\state.js       -> governance persistence retired
    package.json                          -> queue scripts removed

## FILES/FOLDERS ARCHIVED

`GCE_ARCHIVE\2026-10-03_LEGACY_ROUTING_HANDOFF_LEDGER_PRE_RESET\`
**679 files, 8.34 MB, `MANIFEST.csv` with SHA-256 per file, 558 unique hashes,
spot-verified against live sources before removal.**

    06_HANDOFFS\                        (289 files, all 19 seat folders + contract)
    03_HANDOFFS\                        (voice-disconnected UI — NOT DELETED)
    06_OUTBOX\  06_OUTBOX_archive\  session-headers\
    10_SESSIONS\  event-ledger\
    routing_state.json  control-plane-state\
    routing-machine\    footer.js state.js sessionFrame.js queueRefresh.js
                       handoff_registry_producer.js registry.js* index.js* test\
    queueProjection.js  start-queue-watch.cmd
    queue-refresh.log .err.log .pid
    legacy-projected-queue-rows\        (the 38 legacy gce-hq records)
    legacy-queue_local.json  legacy-prune-archive\
    write-findings.ps1  GCE_Findings\
    voice-bridge-v3.1-consolidated\  voice-bridge-v3\  voice-bridge-baseline-20260930\
    voice-bridge-superseded-source\    (src tests docs + config/launchers;
                                         .venv/.env/.git deliberately excluded)

`*` registry.js / index.js / test\ are ARCHIVE COPIES. The originals stay live —
registry.js is the MODEL != SEAT enforcer and is required.

Rollback points: v3-build git `82c9ae3` (pre-reset) and `447faa0` (pre-repair).

## FILES/FOLDERS DELETED

**None.** Everything removed from the live path was moved to the archive after
its archived copy was verified present. The removal script refuses to delete any
item whose archive copy is missing (`blocked=0` of 27 attempted).

---

## LEGACY MACHINERY STILL PRESENT + WHY

1. **`command-center\routing\registry.js` + `seat_registry.json`** — REQUIRED.
   The MODEL != SEAT validator. The one piece of the legacy routing system that
   still enforces something real. 57/57 tests green.

2. **`command-center\routing\footer.js` / `state.js` / `sessionFrame.js`** — the
   DevPad front-end (`public\renderer.js:750,764`) still calls
   `/api/routing/state` and `/api/routing/load`. Removing them would break a
   separate live product, which is outside this job. Their **persistence** is
   retired and no seat emits a footer any more, so they are inert for routing.

3. **`ai-inbox` + `inbox-mcp`** — KEEP as instructed. Independent live seat bus,
   PID 24164. No longer read by the queue (it was the producer's correlation
   source).

4. **VoiceBridge `data/transcripts`, `data/shadow-log`, `latest_logs`** — the
   G6 durable-transcript and engine-health surfaces. Unrelated to the queue.

5. **`voice-bridge\` frozen tree** — retained for `.venv`/`.env`/`.git` and
   provenance. It is no longer referenced by the launcher, the config, or any
   code path.

## DUPLICATE TREE FINAL STATE

    voice-bridge-v3-build         LIVE PRODUCT (5189 files incl .venv)
    voice-bridge                  RETAINED runtime assets only; source archived
    voice-bridge-v3               ARCHIVED
    voice-bridge-v3.1-consolidated ARCHIVED
    voice-bridge-baseline-20260930 ARCHIVED

One live product tree. No peer "current-ish" trees remain.

## AGENTS.md / ROUTER CLEANUP SUMMARY

**Preserved untouched:** identity, role, ownership, OWNS/DOES NOT OWN, seat
principle, authority boundary, specialization, STOP/CHECKPOINT conditions,
evidence discipline, referent addendum, MODEL != SEAT, pronoun metadata, rosters.

**Retired (5 files):** the fenced ```gce.routing``` footer emission block —
`routing_status`, `route_type`, `gate`, `next_route`, `blocker_route`,
session `confidence`. Replaced with the completion-artifact return contract.

**Repointed (5 files):** paths that no longer resolve after archival.

**Deliberately NOT changed — reported as residual, needs Don/Coda:**
- the `NO-CURRENT-ITEM RULE` ("assigned by durable current handoff") in the
  VNEXT+ CONTROL blocks
- `NEXT ROUTE:` / gate-progression vocabulary in session-footer schemas
- the `HANDSHAKE / CABLE CAR` sections listing routing fields for handoffs

These live inside Don-approved target artifacts stamped *"DON-AUTHORIZED
IMPLEMENTATION TARGET / NOT CURRENT UNTIL PROMOTED"*. Rewriting them is a
governance decision owned by Don/Coda, not a plumbing fix. Flagged, not touched.

---

## TEST RESULTS

### TEST A — COMPLETION → QUEUE: **PASS**
Controlled Nico completion with **no project and no workstream** was accepted
(legacy filters would have dropped it for `project-missing`).
- exactly one item: yes
- correct source / subject / artifact: yes
- duplicate on resubmit: none (reported as duplicate)
- same work under a **different id**: none (content-key dedup)
- no legacy metadata requirement: confirmed
- survived >30s and many refresh cycles: confirmed (TEST D below)

### TEST B — ARCHIVE: **PASS**
- disappeared from active: yes
- archive state persisted: yes, ledger event written
- source artifact retained: yes, file untouched
- restart: item did not resurrect; fresh process reports active=[ACCEPT-3] only

### TEST C — HANDOFF: **PASS**
- second completion produced exactly one active item
- payload produced, non-empty, carries the result body
- payload carries lineage to the source queue item
- source auto-archived **only after** payload verification
- restart: source stayed archived, payload still present and usable
- payload byte-verified: 1258 bytes with the full result body embedded

### TEST D — LIVE PRODUCT: **PASS**
- launched from `voice-bridge-v3-build\.venv` — no borrow from the frozen tree
- `.env` loaded from the v3-build tree; key length verified, **value never printed**
- self-test: **26/26 checks passed**
- app launches, mic resolves (`Microphone (5- USB PnP Audio De`, index 1)
- STT works — transcripts persisted, V3 engine live, shadow log written
- health line + automatic recovery work
- queue panel mounted, no `queue panel unavailable` error
- **backdated item (`created_at` 2026-10-01) survived many 30s refresh cycles
  and is still ACTIVE.** Under the legacy rule it was archived on the first
  refresh. This is the decisive proof the age rule is gone.
- detached relaunch survives; state intact after restart (active=2, archived=2)

### TEST E — LEGACY ISOLATION: **PASS**
21/21 retired surfaces verified absent from the live path, then a fresh
completion was ingested successfully. All 27 removals confirmed gone.
No legacy queue machinery running anywhere (`queueRefresh` /
`handoff_registry_producer`: no processes).

### ACCEPTANCE SUITE: **30/30 PASS**
`tests\test_queue_acceptance.py` — full flow in an isolated queue root.

---

## FAILURES / WORKAROUNDS

**F-1 — Acceptance suite: 3 failures on first run.**
- EXPECTED: active count 0 after restart
- OBSERVED: active count 1
- EVIDENCE: sections 5 and 6 of the suite
- FIRST BREAK: my own assertion, section 5
- ROOT CAUSE: **test defect, not a product defect.** Section 4 deliberately
  submits ACCEPT-3 and asserts a failed handoff leaves it ACTIVE. Section 5 then
  asserted the queue was empty — the two expectations contradict each other.
  All three failures were downstream of that contradiction.
- CHANGE MADE: replaced the three wrong assertions with the correct invariant
  ("active == [ACCEPT-3] only; ACCEPT-1 and ACCEPT-2 did not resurrect;
  refused artifact changed nothing"), so the check would actually detect a real
  regression instead of asserting something impossible.
- RETEST: 30/30 PASS.

**W-1 — Tool-timeout killed the first bridge launch.** The shell tool terminated
the process tree at 120s while the bridge was mid-session. Not a product fault;
relaunched fully detached via `Start-Process` without redirection, which is
stable. Recorded because the first launch's log tail contains dictation text.

**W-2 — AssemblyAI DNS blips during the run** (`getaddrinfo failed`, 1011
keepalive timeouts). Pre-existing, in `capture.py` / `_supervisor`, self-
recovering ("recovery succeeded"), present in the log before this pass. Not
caused by the reset. Flagged as a standing defect.

**W-3 — Live voice traffic was captured during testing.** Don's dictation
appears in `latest_logs\bridge.log` and the transcripts directory. That is the
product working normally; noted so it is not mistaken for injected content.

## OPEN DEFECTS

1. **AssemblyAI connection instability** (pre-existing). DNS resolution failures
   and 1011 keepalive timeouts cause `CAPTURE HEALTH FAULT` cycles. The
   supervisor recovers every time, but the mic does drop. `capture.py` /
   `voice_bridge.py:1051`.
2. **`voice-bridge\` frozen tree still on disk** with `.venv` (7842 files). Not
   a dependency, not deleted — deletion is a separate decision.
3. **DevPad routing substrate still live** (`footer.js` / `state.js` /
   `sessionFrame.js`) because the front-end consumes it. Inert for the queue.
   If the DevPad's next-hop highlighting is retired, those three files and four
   `/api/routing/*` endpoints can be removed cleanly.
4. **VNEXT+ workflow vocabulary persists** in seat target artifacts (NO-CURRENT-
   ITEM RULE, NEXT ROUTE, gate progression). Requires a Don/Coda decision — see
   the cleanup summary.
5. **`voice-bridge-v3-build\tools\repoint_config.py`** is a one-shot migration
   script. Harmless, kept for provenance, but it is not part of the runtime.
6. `queue\README.md` describing the old producer contract no longer exists in
   the live tree (it lived in the frozen tree and is archived). A short README
   describing the new contract would help the next operator — not written, as it
   was not requested.

---

## EXACT NEXT ACTION

**Don: open the VoiceBridge queue panel and press ARCHIVE on the two remaining
test items.**

    TEST-D-20261001-NICO-SURVIVAL-003    (backdated survival proof)
    TEST-E-20261004-NICO-LEGACY-ISOLATION-004  (legacy isolation proof)

Both are controlled test fixtures, not real work. Archiving them leaves the
queue empty and demonstrates the button in the real GUI — the one thing I could
not click myself. VoiceBridge is already running (PID 18868, 5412).

Then, for real use: a seat writes a completion artifact and runs

    cd C:\Users\Dekan AI Brother\GCE_DON\voice-bridge-v3-build
    .venv\Scripts\python.exe -m src.completion submit <artifact.json>

**Recommended after that:** decide the four residual items (open defects 1, 3, 4
and the frozen-tree deletion) — items 3 and 4 are the only things still carrying
obsolete workflow vocabulary.

================================================================================
END PASS 2 IMPLEMENTATION RETURN
Nico / Space Bunny · 2026-10-04 · under Don authority
================================================================================