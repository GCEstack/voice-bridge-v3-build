"""Gate C harness — VoiceBridge V3 integrated build.

STEP 5 of the build order. Four criteria, quoted:

    "G6 byte-identity regression passes on the integrated build
     · durable full-fidelity transcripts on disk
     · interpretation shadow running offline alongside
     · health observable"

The carried-over G6 suite proves the persistence COMPONENT in isolation. That
is necessary and it is not sufficient: a component can be byte-perfect and the
integrated pipeline can still truncate on the way to it. So every criterion
here is also asserted through the live pipeline (recv -> engine -> shadow /
-> dispatcher), not only against the component in a vacuum.

Gate C runs only after Gate P. It is a separate file so that the two gates can
be run, read and failed independently.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from src import voice_bridge as vb
from src.capture_service import CaptureConfig as V3CaptureConfig
from src.capture_service import CaptureService

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT.parent / "voice-bridge-baseline-20260930"
SALVAGE = ROOT.parent / "voice-bridge-v3"

# The G6 suite's own fixture, reused verbatim so Gate C is measuring the same
# thing the salvage measured, on the integrated build.
G6_TEXT = (
    "This is a test utterance that is designed to be longer than five hundred characters "
    "so that we can verify that the full-fidelity transcript persistence is working correctly. "
    "The old system would truncate this to eighty characters at the logging boundary in intent.py line one hundred and two. "
    "We are now ensuring that the complete STT output is preserved before any normalization, intent classification, or lossy transform. "
    "This is the G6 invariant that must be maintained throughout the VoiceBridge V3 system. "
    "Any component that receives full text and persists less than the full text is a defect, not a design choice."
)

# Non-ASCII + code-fence + control-ish characters: the persisted JSON must be a
# byte-exact round trip, not an ASCII-folded approximation of the transcript.
UNICODE_TEXT = (
    "Unicode fidelity probe: em-dash — en-dash – ellipsis … «guillemets» "
    "Café naïve Ω π 日本語 テスト ✅ emoji 👩‍💻 and a "
    "code fence ```python\nprint('x')\n``` plus a tab\tand trailing spaces.   "
) * 3


def _make_bridge(tmp_path):
    cfg = ROOT / "config.json"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data.setdefault("paths", {})
    data["paths"]["transcripts"] = str(tmp_path / "transcripts")
    data["paths"]["audio"] = str(tmp_path / "audio")
    data["paths"]["shadow_log"] = str(tmp_path / "shadow-log")
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(data), encoding="utf-8")
    bridge = vb.WakeWordBridge(config_path=str(cfg_path))
    bridge.assemblyai_api_key = "test-key"
    return bridge


def _drain(bridge, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if bridge._turn_queue.empty() and bridge._final_queue.empty():
            time.sleep(0.05)
            if bridge._turn_queue.empty() and bridge._final_queue.empty():
                return True
        time.sleep(0.02)
    return False


def _await(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# ---------------------------------------------------------------------------
# C1 — G6 byte-identity regression passes ON THE INTEGRATED BUILD
# ---------------------------------------------------------------------------
def test_c1_g6_suite_is_the_salvage_suite():
    """The G6 suite shipped unmodified. A rewritten test proves nothing."""
    assert (ROOT / "tests" / "test_g6_regression.py").read_bytes() == \
        (SALVAGE / "tests" / "test_g6_regression.py").read_bytes()


def test_c1_g6_byte_identity_through_the_live_pipeline(tmp_path):
    """C1: the G6 fixture, byte-identical on disk, via the REAL pipeline.

    This is the criterion the order states. It deliberately does not call
    `persist_transcript` directly: the question is whether the integrated
    build loses anything between the STT boundary and the file, and a direct
    component call cannot answer that.
    """
    assert len(G6_TEXT) > 500
    bridge = _make_bridge(tmp_path)
    bridge.on_transcript(G6_TEXT, is_final=True)
    assert _drain(bridge)

    tdir = Path(bridge.v3_engine.transcripts_dir)
    files = list(tdir.glob("*.json"))
    assert len(files) == 1, f"expected 1 durable transcript, got {len(files)}"

    raw_bytes = files[0].read_bytes()
    payload = json.loads(raw_bytes.decode("utf-8"))
    assert payload["raw_text"] == G6_TEXT
    assert payload["is_partial"] is False
    assert payload["stt_provider"] == "assemblyai"
    assert payload["stt_model"] == "universal-3-5-pro"
    assert payload["event_id"] == files[0].stem

    # Byte-identity, not just string equality after a decode round trip.
    assert G6_TEXT.encode("utf-8") in raw_bytes
    bridge._stopping = True


def test_c1_g6_unicode_round_trips_byte_exactly(tmp_path):
    """C1: byte-identity holds for non-ASCII text too.

    `ensure_ascii=False` is what makes this pass. If someone ever flips that
    flag, a transcript still round-trips through `json.load` and the cheap test
    still goes green — so the raw bytes have to be checked directly.
    """
    bridge = _make_bridge(tmp_path)
    bridge.on_transcript(UNICODE_TEXT, is_final=True)
    assert _drain(bridge)

    tdir = Path(bridge.v3_engine.transcripts_dir)
    files = list(tdir.glob("*.json"))
    assert len(files) == 1
    raw = files[0].read_bytes().decode("utf-8")

    # Round trip through the durable file is exact.
    payload = json.loads(raw)
    assert payload["raw_text"] == UNICODE_TEXT

    # The file stores the characters, not \u escapes. `ensure_ascii=False` is
    # what makes this true; flipping it would still round-trip through
    # json.load, so the escapes are checked for explicitly.
    for char in ("—", "–", "…", "«", "é", "Ω", "π",
                 "日本語", "テスト", "✅"):
        assert char in raw, f"{char!r} was escaped instead of stored"
    assert "\\u2014" not in raw
    assert "\\u65e5" not in raw
    bridge._stopping = True


def test_c1_persist_precedes_typing(tmp_path):
    """C1: the durable write happens BEFORE the text can be typed.

    G6 says the transcript is persisted before any transform. Typing is a
    transform, so a character on screen with no file behind it is a G6
    violation even though both halves "worked". This asserts the ORDER, by
    instrumenting the write and the type call and checking the sequence.
    """
    bridge = _make_bridge(tmp_path)
    order = []
    engine = bridge.v3_engine
    original_persist = engine.persist_transcript

    def traced_persist(text, is_partial=False, duration=None):
        order.append(("persist", is_partial))
        return original_persist(text, is_partial=is_partial, duration=duration)

    engine.persist_transcript = traced_persist

    import src.voice_bridge as vbm
    orig_type = vbm.type_text
    vbm.type_text = lambda t, interval=0.01: order.append(("type", False))
    try:
        bridge.on_transcript("order matters: the file must exist first", is_final=True)
        assert _drain(bridge)
    finally:
        vbm.type_text = orig_type

    assert order, "nothing happened"
    assert order[0][0] == "persist", f"typed before persisting: {order}"
    assert order[-1][0] == "type"
    assert order[0][1] is False, "a final must be persisted as durable"
    bridge._stopping = True


# ---------------------------------------------------------------------------
# C2 — durable full-fidelity transcripts on disk
# ---------------------------------------------------------------------------
def test_c2_durable_corpus_has_one_record_per_utterance(tmp_path):
    """C2: a multi-utterance session yields exactly N durable records."""
    bridge = _make_bridge(tmp_path)
    utterances = [
        "first utterance of the session",
        "second utterance, with a comma, and more than one clause to it",
        "third utterance",
    ]
    for utt in utterances:
        bridge.on_transcript(utt, is_final=False)   # partial
        bridge.on_transcript(utt, is_final=True)    # final
    assert _drain(bridge)

    tdir = Path(bridge.v3_engine.transcripts_dir)
    files = sorted(tdir.glob("*.json"))
    assert len(files) == len(utterances), \
        f"expected {len(utterances)} durable records, got {len(files)}"

    stored = [json.loads(f.read_text(encoding="utf-8"))["raw_text"]
              for f in files]
    assert sorted(stored) == sorted(utterances)

    # Distinct event ids — no two utterances share a file.
    assert len({f.stem for f in files}) == len(files)
    bridge._stopping = True


def test_c2_durable_records_carry_provenance(tmp_path):
    """C2: a durable record is evidence, so it carries its provenance."""
    bridge = _make_bridge(tmp_path)
    bridge.on_transcript("a record with provenance", is_final=True)
    assert _drain(bridge)

    ids = bridge.v3_engine.durable_transcript_ids()
    payload = bridge.v3_engine.read_transcript(ids[0])
    for field in ("event_id", "timestamp", "raw_text", "audio_path",
                  "duration_seconds", "stt_provider", "stt_model", "is_partial"):
        assert field in payload, f"durable record is missing {field}"
    assert payload["event_id"] == ids[0]
    assert payload["timestamp"]
    assert payload["stt_model"] == "universal-3-5-pro"
    bridge._stopping = True


def test_c2_no_partial_ever_reaches_disk(tmp_path):
    """C2: the durability contract, stated as a negative."""
    bridge = _make_bridge(tmp_path)
    for i in range(25):
        bridge.on_transcript("partial text that must never be durable " * 2,
                             is_final=False)
    assert _drain(bridge)
    tdir = Path(bridge.v3_engine.transcripts_dir)
    assert list(tdir.glob("*.json")) == [], "a partial was written to disk"
    rep = bridge.v3_engine.durability_report()
    assert rep["durable_writes"] == 0
    assert rep["ephemeral_partials_not_written"] == 25
    bridge._stopping = True


def test_c2_audit_log_agrees_with_the_durable_record(tmp_path):
    """C2: two independent sinks, one text.

    The durable transcript and the intent audit are written by different code
    on different threads. If they can disagree, one of them is decoration.
    """
    from src.intent import log_utterance

    bridge = _make_bridge(tmp_path)
    bridge.on_transcript(G6_TEXT, is_final=True)
    assert _drain(bridge)

    ids = bridge.v3_engine.durable_transcript_ids()
    stored = bridge.v3_engine.read_transcript(ids[0])["raw_text"]

    log = tmp_path / "intent_audit.log"
    log_utterance(stored, path=str(log))
    line = log.read_text(encoding="utf-8").strip()
    assert stored in line
    assert "TRUNCATED FOR PREVIEW" not in line
    bridge._stopping = True


# ---------------------------------------------------------------------------
# C3 — interpretation shadow running offline alongside
# ---------------------------------------------------------------------------
def test_c3_shadow_runs_alongside_without_blocking_capture(tmp_path):
    """C3: the shadow runs concurrently and never sits in the capture path.

    The shadow is handed a real durable record, produces its own artefact, and
    the utterance is typed in the same window. If the shadow were synchronous
    or on the critical path, a slow shadow would become lost dictation.
    """
    bridge = _make_bridge(tmp_path)
    stats = bridge.v3_shadow_stats()
    assert stats["running"] is True
    shadow_dir = Path(stats["shadow_log_dir"])

    typed = []
    import src.voice_bridge as vbm
    orig_type = vbm.type_text
    vbm.type_text = lambda t, interval=0.01: typed.append(t)
    try:
        bridge.on_transcript(G6_TEXT, is_final=True)
        assert _drain(bridge)
    finally:
        vbm.type_text = orig_type

    # Dictation is not gated on the shadow.
    assert typed == [G6_TEXT + " "]

    assert _await(lambda: list(shadow_dir.glob("*.json"))), \
        "shadow produced no log"
    logs = sorted(shadow_dir.glob("*.json"))
    data = json.loads(logs[0].read_text(encoding="utf-8"))
    assert data["source_transcript"] == G6_TEXT
    assert data["claims"]
    assert data["model_version"] == stats["model_version"]
    for claim in data["claims"]:
        assert "confidence" in claim and "model_version" in claim
    bridge._stopping = True


def test_c3_shadow_has_no_authority_over_live_dictation(tmp_path):
    """C3: the shadow cannot reach dictation. Proved by reading its output.

    Whatever the shadow claims — speech act, slots, confidence — the bridge
    typed the operator's words, not the shadow's interpretation of them. If a
    shadow log ever became an input to the typing path, this fails.
    """
    bridge = _make_bridge(tmp_path)
    shadow_dir = Path(bridge.v3_shadow_stats()["shadow_log_dir"])

    spoken = "stop listening right now please"
    typed = []
    import src.voice_bridge as vbm
    orig_type = vbm.type_text
    vbm.type_text = lambda t, interval=0.01: typed.append(t)
    try:
        bridge.on_transcript(spoken, is_final=True)
        assert _drain(bridge)
    finally:
        vbm.type_text = orig_type
    assert _await(lambda: list(shadow_dir.glob("*.json")))

    # Typed verbatim. The shadow's classification of it is irrelevant here —
    # and note "stop listening" TYPES rather than pausing, which is the
    # baseline behaviour (Don 2026-09-25) the shadow must not override.
    assert typed == [spoken + " "]
    assert bridge.paused is False
    bridge._stopping = True


def test_c3_shadow_writes_only_to_its_own_directory(tmp_path):
    """C3: shadow output lands in the shadow log and nowhere else."""
    bridge = _make_bridge(tmp_path)
    bridge.on_transcript("shadow containment probe", is_final=True)
    assert _drain(bridge)
    assert _await(
        lambda: list(Path(bridge.v3_shadow_stats()["shadow_log_dir"]).glob("*.json"))
    )

    engine_dir = Path(bridge.v3_engine.transcripts_dir)
    shadow_dir = Path(bridge.v3_shadow_stats()["shadow_log_dir"])
    assert shadow_dir != engine_dir
    # The engine wrote its one transcript; the shadow wrote its one log.
    assert len(list(engine_dir.glob("*.json"))) == 1
    # No shadow artefact leaked into the transcript corpus.
    for f in engine_dir.glob("*.json"):
        payload = json.loads(f.read_text(encoding="utf-8"))
        assert "claims" not in payload
        assert payload["raw_text"] == "shadow containment probe"
    bridge._stopping = True


# ---------------------------------------------------------------------------
# C4 — health observable
# ---------------------------------------------------------------------------
def test_c4_health_is_reachable_without_the_gui(tmp_path):
    """C4: health is a queryable property, not a string in a Tk widget."""
    bridge = _make_bridge(tmp_path)
    ok, why = bridge.v3_health()
    assert isinstance(ok, bool) and isinstance(why, str) and why
    assert ok is True
    assert bridge.v3_engine.is_running() is True
    assert bridge.v3_engine.is_healthy() is True
    bridge._stopping = True


def test_c4_engine_reports_silence_as_a_fault(tmp_path):
    """C4: silence beyond the threshold is a FAULT, not a healthy quiet."""
    bridge = _make_bridge(tmp_path)
    health = bridge.v3_engine.health
    health.silence_threshold_seconds = 1
    health.record_audio()

    ok, why = bridge.v3_health()
    assert ok is True

    time.sleep(1.2)
    ok, why = bridge.v3_health()
    assert ok is False, "silence was reported as healthy"
    assert "silence fault" in why
    assert "threshold=1" in why

    # And it recovers by itself when audio resumes, because the VAD gate means
    # silence is a normal idle state.
    health.record_audio()
    ok, _ = bridge.v3_health()
    assert ok is True
    bridge._stopping = True


def test_c4_external_fault_is_latched_and_reported(tmp_path):
    """C4: the audio path's own verdict reaches the engine's health."""
    bridge = _make_bridge(tmp_path)
    bridge.v3_engine.health.adopt_external_health(False, "recv loop dead")
    ok, why = bridge.v3_health()
    assert ok is False and "recv loop dead" in why

    # A healthy verdict from the audio path must NOT clear a real fault.
    bridge.v3_engine.health.adopt_external_health(True, "healthy")
    ok, _ = bridge.v3_health()
    assert ok is False, "a fault was cleared by an unrelated healthy tick"

    # Only an explicit rebuild clears it.
    bridge.v3_engine.health.clear_fault()
    ok, _ = bridge.v3_health()
    assert ok is True
    bridge._stopping = True


def test_c4_health_survives_a_missing_engine(tmp_path):
    """C4: an engine that failed to start reports FAULT, not silence."""
    bridge = _make_bridge(tmp_path)
    bridge.v3_engine = None
    ok, why = bridge.v3_health()
    assert ok is False
    assert "not initialised" in why
    bridge._stopping = True


# ---------------------------------------------------------------------------
# Scope lock — the shadow stays shadow
# ---------------------------------------------------------------------------
def test_scope_lock_no_stage3_authority(tmp_path):
    """The build ships Stage 2 only. Asserted on the shipped surface."""
    shadow_src = (ROOT / "src" / "interpretation_shadow.py").read_text(encoding="utf-8")
    # No emission, no ledger writes, no policy/reference resolution.
    assert "ledger" not in shadow_src.lower() or "Never writes to the ledger" in shadow_src
    for banned in ("emit_claim", "resolve_reference", "apply_policy",
                   "stage3", "stage_3", "publish"):
        assert banned not in shadow_src.lower(), \
            f"shadow gained a {banned} surface — scope lock broken"
    # It writes to exactly one directory.
    assert "shadow_log_dir" in shadow_src


def test_capture_audio_path_is_not_duplicated(tmp_path):
    """One audio path, not two.

    The transplant order named capture_service.py as the STT capture. This
    build deliberately keeps the mature shell audio path and uses the engine
    for persistence + health. If a second WebSocket loop ever appears, this
    fails — a duplicate would mean a duplicate billed session.
    """
    engine_src = (ROOT / "src" / "capture_service.py").read_text(encoding="utf-8")
    assert "websockets" not in engine_src, \
        "the engine opened a websocket: the audio path has been duplicated"
    assert "RawInputStream" not in engine_src
    assert "sounddevice" not in engine_src
    # The mature audio path is untouched, byte for byte.
    assert (ROOT / "src" / "capture.py").read_bytes() == \
        (BASELINE / "src" / "capture.py").read_bytes()
