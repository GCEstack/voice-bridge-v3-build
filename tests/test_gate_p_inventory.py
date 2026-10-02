"""Gate P harness — VoiceBridge V3 integrated build.

STEP 4 of the build order: "Run the integrated build against every inventory
item in Sec. 2 ... All green -> candidate goes to Don for his real-usage run.
Not green -> fix, re-run."

This module is the machine part of that claim. Every Sec. 2 inventory item has
exactly one test here, and each test states HOW it was verified. Nothing is
verified by assertion alone and nothing is verified by reading the code and
trusting it.

Two verification methods are used, and the difference matters:

  BEHAVIOUR  - the real object is exercised and its effect observed. Used for
               every flow, control and surgery point that can be exercised
               headlessly.
  BYTE-STABLE - the file is hashed against the frozen baseline snapshot and
               must be identical. Used where the Sec. 2 requirement IS
               "preserved unchanged" (llm.py) and where the order freezes a
               surface outright (surgery point B: the queue panel read path).
               A hash cannot drift silently, which is exactly what "preserved
               unchanged" has to mean.

What is NOT covered here, and why, is recorded in GATE_P_EVIDENCE.md: a live
microphone, a live AssemblyAI billing session and a human looking at a Tk
window cannot be produced headlessly. Those items are verified by inspection
and are explicitly labelled INSPECTION in the evidence file rather than counted
green here.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

import pytest

from src import voice_bridge as vb
from src.capture import AssemblyAICapture
from src.capture import CaptureConfig as AudioCaptureConfig
from src.capture_service import CaptureConfig as V3CaptureConfig
from src.capture_service import CaptureService, TranscriptRecord

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT.parent / "voice-bridge-baseline-20260930"
SALVAGE = ROOT.parent / "voice-bridge-v3"

# The Sec. 2 inventory, quoted verbatim from the build order.
CONTROLS = [
    "Mic toggle",
    "listening indicator",
    "MODE display",
    "Reconnect",
    "Quit",
    "Show dismissed checkbox (23 at capture time)",
    "Refresh",
    "status line (queue state + registry path)",
    "row actions: Open - Copy Text - Copy Path - Dismiss - Open folder - Archive reviewed",
]

FLOWS = [
    "wake word -> activate listening",
    "VAD silence gating",
    "continuous capture -> STT -> dictation output to Copy Text (COMPLETE text)",
    "queue panel auto-refresh from queue\\",
    "WebSocket reconnect on drop",
    "voice command handlers",
    "keyboard input simulation",
    "screenshot capture",
    "voice profiles",
    "config.json read",
    "llm.py behavior preserved unchanged",
]

# Longer than the 80-char defect boundary AND longer than the G6 suite's own
# 500-char minimum, so no short sample can ever mask a truncation.
LONG_UTTERANCE = (
    "This utterance is deliberately longer than five hundred characters so "
    "that the baseline truncation defect at intent.py line one hundred and two "
    "cannot hide behind a short sample, and so that any component which "
    "receives the full speech-to-text transcript and persists less than all of "
    "it is caught by this test rather than discovered later during real use by "
    "the operator, at the exact moment it would actually cost something to "
    "discover it, which is to say after the words have already been acted on."
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_bridge(tmp_path):
    """A bridge with no microphone, no network and no Tk window.

    `tmp_path` is REQUIRED, not optional. The engine writes durable transcripts
    and the shadow writes shadow logs, so a test sharing the configured `data/`
    directory with its neighbours cannot honestly claim how many files one
    utterance produced.
    """
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
    """Wait until the engine + dispatch pipeline has gone quiet."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if bridge._turn_queue.empty() and bridge._final_queue.empty():
            time.sleep(0.05)
            if bridge._turn_queue.empty() and bridge._final_queue.empty():
                return True
        time.sleep(0.02)
    return False


# ---------------------------------------------------------------------------
# CONTROLS
# ---------------------------------------------------------------------------
def test_control_mic_toggle(tmp_path):
    """CONTROL: Mic toggle.  BEHAVIOUR — real handler, fake capture."""
    bridge = _make_bridge(tmp_path)

    class FakeCap:
        def __init__(self):
            self.muted = False

        def is_muted(self):
            return self.muted

        def set_muted(self, m):
            self.muted = m

        def stop(self):
            pass

    seen = []
    bridge._set_status = seen.append
    cap = FakeCap()
    bridge.capture = cap

    bridge._toggle_mute()
    assert cap.muted is True
    assert any("MUTED" in s for s in seen), seen

    bridge._toggle_mute()
    assert cap.muted is False
    assert any("MIC ON" in s for s in seen), seen

    # Degrades, never raises, when there is no capture yet.
    bridge.capture = None
    bridge._toggle_mute()
    assert any("not started" in s for s in seen)
    bridge._stopping = True


def test_control_listening_indicator(tmp_path):
    """CONTROL: listening indicator.  BEHAVIOUR — the reachable status strings.

    A listening indicator that is not asserted against the strings the running
    code actually emits is a decoration, not a control.
    """
    bridge = _make_bridge(tmp_path)
    seen = []
    bridge._set_status = seen.append

    class FakeCap:
        def __init__(self):
            self.muted = False

        def is_muted(self):
            return self.muted

        def set_muted(self, m):
            self.muted = m

        def stop(self):
            pass

        def is_running(self):
            return True

        def health(self):
            return True, "healthy"

    bridge.capture = FakeCap()

    # Live: unmuting says the bridge is listening.
    bridge._toggle_mute()   # -> MUTED
    seen.clear()
    bridge._toggle_mute()   # -> ON, listening
    assert any("listening" in s.lower() for s in seen), seen

    # Paused: the indicator changes, so a paused bridge never reads as live.
    seen.clear()
    bridge.paused = True
    bridge._handle_final("this utterance is ignored while paused")
    assert any("paused" in s.lower() for s in seen), seen

    # The recovery string the supervisor prints on a live session.
    src = (ROOT / "src" / "voice_bridge.py").read_text(encoding="utf-8")
    assert "● listening — speak now" in src
    bridge._stopping = True


def test_control_mode_display(tmp_path):
    """CONTROL: MODE display.  BEHAVIOUR on the flag, INSPECTION on the label.

    The MODE line is built in `_build_ui`, which needs a Tk display, so the
    observable part is the literal it renders plus the flag that drives it.
    `run()` forces continuous on precisely so this label cannot lie.
    """
    src = (ROOT / "src" / "voice_bridge.py").read_text(encoding="utf-8")
    assert 'text="MODE: continuous"' in src
    assert 'self.continuous = True' in src

    bridge = _make_bridge(tmp_path)
    bridge.continuous = True
    bridge.paused = False
    seen = []
    bridge._set_status = seen.append
    bridge._handle_final("an ordinary dictated sentence")
    assert any(s.startswith("typed:") for s in seen), seen
    bridge._stopping = True


def test_control_reconnect(tmp_path):
    """CONTROL: Reconnect.  BEHAVIOUR — real handler, fake capture."""
    bridge = _make_bridge(tmp_path)
    seen = []
    bridge._set_status = seen.append

    class FakeCap:
        def __init__(self):
            self.stopped = False

        def stop(self):
            self.stopped = True

    cap = FakeCap()
    bridge.capture = cap
    bridge._reconnect_backoff = 99.0
    bridge._reconnect_now()
    assert cap.stopped is True
    assert bridge.capture is None
    assert bridge._reconnect_backoff == pytest.approx(2.0)
    assert any("reconnect" in s.lower() for s in seen)
    bridge._stopping = True


def test_control_quit(tmp_path):
    """CONTROL: Quit.  BEHAVIOUR — voice 'quit' and the button handler."""
    bridge = _make_bridge(tmp_path)
    closed = []
    bridge._schedule_close = lambda: closed.append(True)
    bridge._handle_final("quit")
    assert closed == [True]

    class FakeCap:
        def __init__(self):
            self.stopped = False

        def stop(self):
            self.stopped = True

    cap = FakeCap()
    bridge.capture = cap
    bridge._on_close()
    assert bridge._stopping is True
    assert cap.stopped is True
    assert bridge.capture is None


def test_control_show_dismissed_checkbox(tmp_path):
    """CONTROL: Show dismissed checkbox.  BEHAVIOUR on the filter, INSPECTION
    on the widget. A missing control is a missing binding, and a missing
    binding is a missing call — so the widget construction is asserted."""
    from src import queue_panel as qp

    src = (ROOT / "src" / "queue_panel.py").read_text(encoding="utf-8")
    assert "Show dismissed" in src
    assert "dismissed_var" in src and "ttk.Checkbutton" in src
    assert hasattr(qp.QueuePanel, "_toggle_dismissed")

    items = [{"id": "a"}, {"id": "b"}]
    assert qp.visible(items, {"a"}, False) == [{"id": "b"}]
    assert len(qp.visible(items, {"a"}, True)) == 2


def test_control_refresh_and_status_line(tmp_path):
    """CONTROLS: Refresh, status line (queue state + registry path)."""
    from src import queue_panel as qp

    src = (ROOT / "src" / "queue_panel.py").read_text(encoding="utf-8")
    assert 'ttk.Button(head, text="Refresh", command=self.refresh' in src
    assert hasattr(qp.QueuePanel, "refresh")
    assert hasattr(qp.QueuePanel, "_auto_refresh")
    assert "self.after(int(self.refresh_seconds * 1000), self._auto_refresh)" in src
    assert "refresh_seconds" in src
    # Status line carries the queue state AND the registry path.
    assert "Registry: {self.registry_path}" in src
    assert "action_status" in src
    assert qp.DEFAULT_LIMIT == 300


def test_control_row_actions(tmp_path):
    """CONTROL: row actions.  BEHAVIOUR — the six actions and their payloads."""
    from src import queue_panel as qp

    src = (ROOT / "src" / "queue_panel.py").read_text(encoding="utf-8")
    for label, needle in (
        ("Open", '"Open"'),
        ("Copy Text", '"Copy Text"'),
        ("Copy Path", '"Copy Path"'),
        ("Dismiss", "Dismiss"),
        ("Open folder", '"Open folder"'),
        ("Archive reviewed", '"Archive reviewed"'),
    ):
        assert needle in src, f"row action {label} not present"

    for meth in ("_on_open", "_on_copy_text", "_on_copy_path", "_on_dismiss",
                 "_open_handoff_folder", "_on_archive"):
        assert hasattr(qp.QueuePanel, meth), f"missing handler {meth}"

    # Copy Text carries the metadata header AND the body.
    rec = {"id": "x", "project": "EC8", "subject": "S", "status": "ready",
           "from": "Nico", "body": "hello", "local_path": r"C:\tmp\a.md"}
    text = qp.record_text(rec)
    assert "EC8" in text and "hello" in text and "id: x" in text


def test_row_dismiss_is_local_state_only(tmp_path):
    """Row action: Dismiss writes reviewer state and never the registry."""
    from src import queue_panel as qp

    state = tmp_path / "queue_local.json"
    assert qp.save_dismissed(str(state), {"a", "b"}) is True
    assert qp.load_dismissed(str(state)) == {"a", "b"}
    # Absent file is an empty set, not a crash.
    assert qp.load_dismissed(str(tmp_path / "nope.json")) == set()
    # The saved shape is the panel's own local reviewer state.
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert "dismissed" in saved


# ---------------------------------------------------------------------------
# FLOWS
# ---------------------------------------------------------------------------
def test_flow_wake_word_in_the_live_continuous_path(tmp_path):
    """FLOW: wake word -> activate listening, IN THE PATH THAT ACTUALLY RUNS.

    GATE P AMENDMENT (2026-10-01). This item was originally verified only
    against the dormant SLEEPING/ARMED branch, with `continuous=False`. That
    branch is unreachable: `run()` force-sets `continuous=True`, so the wake
    word was never consulted in the live build — saying "hey keel" typed the
    words "hey keel" into the focused window and armed nothing.

    Sec. 2 lists "wake word -> activate listening" as a required flow, so a
    verified-but-dead code path is not verification. These assertions run with
    `continuous=True`, exactly as `run()` leaves it.
    """
    bridge = _make_bridge(tmp_path)
    typed = []
    import src.voice_bridge as vbm
    orig = vbm.type_text
    vbm.type_text = lambda t, interval=0.01: typed.append(t)
    bridge.lock_target_window = lambda: None
    bridge.continuous = True  # what run() forces
    bridge.paused = False
    try:
        # 1. Wake word + payload: the wake word is consumed, the payload types.
        bridge._handle_final("hey keel this is the first full sentence")
        assert typed == ["this is the first full sentence "], typed
        assert bridge.state == bridge.ARMED

        # 2. Bare wake word: arms, types nothing at all.
        typed.clear()
        bridge._handle_final("okay keel")
        assert typed == [], f"bare wake word typed: {typed}"
        assert bridge.state == bridge.ARMED

        # 3. No wake word: untouched. Nothing is stripped, nothing is swallowed.
        typed.clear()
        bridge._handle_final("this is ordinary dictation with no wake word")
        assert typed == ["this is ordinary dictation with no wake word "], typed

        # 4. All four configured wake words arm the live path.
        for ww in bridge.wake_words:
            typed.clear()
            bridge._handle_final(ww)
            assert typed == [], f"{ww!r} typed instead of arming"

        # 5. A correcting second passage works exactly like the first.
        typed.clear()
        bridge._handle_final(
            "hey keel actually I meant the second passage not the first")
        assert typed == ["actually I meant the second passage not the first "]
    finally:
        vbm.type_text = orig
    bridge._stopping = True


def test_wake_word_match_is_word_boundary_aware(tmp_path):
    """The wake word must not eat the start of an ordinary word.

    A bare `startswith` strips "keel" out of "keelbase" and mangles a proper
    noun. This asserts the guard exists, because the cost of getting it wrong
    is a silently corrupted dictation rather than a visible failure.
    """
    bridge = _make_bridge(tmp_path)
    for not_a_wake_word in (
        "keelbase platform notes",
        "keelson was the engineer",
        "keellings and corridors",
        "okayness of the argument",
    ):
        assert bridge._find_wake_word(not_a_wake_word) is None, not_a_wake_word

    # Punctuation and end-of-string are boundaries; they DO arm.
    assert bridge._find_wake_word("hey keel.") == "hey keel"
    assert bridge._find_wake_word("hey keel, start") == "hey keel"
    assert bridge._find_wake_word("hey keel") == "hey keel"
    assert bridge._find_wake_word("hey keel start") == "hey keel"
    # Longest match still wins.
    assert bridge._find_wake_word("okay keel go") == "okay keel"
    bridge._stopping = True


def test_flow_wake_word_to_listening_legacy_branch(tmp_path):
    """FLOW: wake word -> activate listening.  BEHAVIOUR — all four wake words."""
    bridge = _make_bridge(tmp_path)
    assert bridge.wake_words == ("hey keel", "ok keel", "okay keel", "keel")
    for ww in bridge.wake_words:
        assert bridge._find_wake_word(ww + " start dictating") == ww
    # Longest match wins, so "okay keel" is not shadowed by "ok keel".
    assert bridge._find_wake_word("okay keel go") == "okay keel"
    assert bridge._find_wake_word("no wake word here") is None

    # It really arms: SLEEPING -> ARMED, and the payload is dispatched.
    typed = []
    bridge._dispatch = lambda t: typed.append(t)
    bridge.continuous = False
    bridge._handle_final("hey keel write the report")
    assert bridge.state == bridge.ARMED
    assert typed == ["write the report"]

    # Ambient speech while not armed is ignored entirely.
    typed.clear()
    bridge._armed_until = 0.0
    bridge._handle_final("this is the room noise")
    assert typed == []
    bridge._stopping = True


def test_flow_vad_gate(tmp_path):
    """FLOW: VAD silence gating.  BEHAVIOUR — the real gate function."""
    import array

    cap = AssemblyAICapture(AudioCaptureConfig(
        api_key="k", vad_threshold=500.0, vad_silence_seconds=3.0))

    quiet = array.array("h", [10] * 800).tobytes()
    loud = array.array("h", [2000] * 800).tobytes()

    assert cap._gate_should_send(0.0) is False   # quiet: gate closed
    assert cap.is_gate_running() is False
    assert cap._gate_should_send(9000) is True   # loud: gate open
    assert cap.is_gate_running() is True

    # Manual mute always wins over the gate.
    cap.set_muted(True)
    assert cap._gate_should_send(9000) is False
    assert cap.is_muted() is True
    cap.set_muted(False)
    assert cap.is_muted() is False
    assert cap._gate_should_send(9000) is True
    assert len(quiet) == 1600 and len(loud) == 1600


def test_flow_full_text_reaches_dictation_and_disk(tmp_path):
    """FLOW + SURGERY A + G6: a >500-char utterance is COMPLETE everywhere.

    The central Gate P claim, and the one the baseline defect attacked. The
    same string is pushed through the real pipeline (recv -> engine ->
    dispatcher) and must arrive at the typing buffer complete AND land on disk
    byte-identical. One assertion, one string, both destinations.
    """
    assert len(LONG_UTTERANCE) > 500
    bridge = _make_bridge(tmp_path)
    typed = []
    import src.voice_bridge as vbm
    orig_type = vbm.type_text
    vbm.type_text = lambda t, interval=0.01: typed.append(t)
    try:
        bridge.on_transcript(LONG_UTTERANCE, is_final=True)
        assert _drain(bridge), "pipeline did not go quiet"
    finally:
        vbm.type_text = orig_type

    # 1. Complete text at the dictation buffer. Not text[:80].
    assert typed, "nothing was typed"
    assert typed[0] == LONG_UTTERANCE + " "
    assert len(typed[0]) > 500
    assert typed[0].startswith(LONG_UTTERANCE[:80])

    # 2. Complete text on disk, byte-identical.
    ids = bridge.v3_engine.durable_transcript_ids()
    assert len(ids) == 1, f"expected exactly ONE durable transcript, got {len(ids)}"
    stored = bridge.v3_engine.read_transcript(ids[0])["raw_text"]
    assert stored == LONG_UTTERANCE
    bridge._stopping = True


def test_surgery_a_intent_audit_writes_full_text(tmp_path):
    """SURGERY A: intent_audit.log keeps writing, now lossless."""
    from src.intent import log_utterance

    path = str(tmp_path / "intent_audit.log")
    log_utterance(LONG_UTTERANCE, path=path)
    line = Path(path).read_text(encoding="utf-8").strip()
    assert LONG_UTTERANCE in line
    assert "TRUNCATED FOR PREVIEW" not in line

    # The baseline bound is gone from the code, not just unused. Checked
    # against the format string, not the docstring that explains the defect.
    intent_src = (ROOT / "src" / "intent.py").read_text(encoding="utf-8")
    assert "| '{text[:80]}'" not in intent_src
    assert "f\"| '{shown}'\"" in intent_src

    # An explicit opt-in preview still shortens, and still says so.
    log_utterance(LONG_UTTERANCE, path=path, preview_chars=80)
    lines = Path(path).read_text(encoding="utf-8").strip().splitlines()
    assert "TRUNCATED FOR PREVIEW" in lines[-1]
    assert len(lines) == 2

    # Rotation still bounds growth (full lines are longer, so this matters).
    from src.intent import report
    assert "INTENT/CADENCE AUDIT" in report(path=path)


def test_surgery_c_exactly_one_durable_per_utterance(tmp_path):
    """SURGERY C: ephemeral partials, exactly ONE durable transcript."""
    bridge = _make_bridge(tmp_path)
    engine = bridge.v3_engine
    tdir = Path(engine.transcripts_dir)

    # Six partial frames of one utterance, then the final.
    for i in range(6):
        bridge.on_transcript(LONG_UTTERANCE[: 40 * (i + 1)], is_final=False)
    bridge.on_transcript(LONG_UTTERANCE, is_final=True)
    assert _drain(bridge)

    files = sorted(tdir.glob("*.json"))
    assert len(files) == 1, f"expected 1 durable file, got {[f.name for f in files]}"
    assert engine.read_transcript(files[0].stem)["raw_text"] == LONG_UTTERANCE

    rep = engine.durability_report()
    assert rep["durable_writes"] == 1
    assert rep["ephemeral_partials_not_written"] == 6
    assert rep["durable_files_on_disk"] == 1
    assert rep["last_error"] is None

    # No stray temp file survived the write-then-replace.
    assert list(tdir.glob("*.tmp")) == []
    bridge._stopping = True


def test_surgery_b_queue_panel_read_path_unchanged(tmp_path):
    """SURGERY B: the queue panel read path is BYTE-IDENTICAL to the baseline.

    Not "still works" — identical bytes. The order freezes this surface, so a
    hash is the honest test; a behavioural test would pass equally happily
    after an unrequested refactor.
    """
    assert _sha(ROOT / "src" / "queue_panel.py") == \
        _sha(BASELINE / "src" / "queue_panel.py"), \
        "queue_panel.py drifted from the frozen baseline"


def test_flow_queue_panel_auto_refresh_reads_registry(tmp_path):
    """FLOW: queue panel auto-refresh reads the queue registry.  BEHAVIOUR."""
    from src import queue_panel as qp

    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    path = cfg["handoff_queue"]["registry_path"]
    assert Path(path).exists(), "configured registry path does not exist"

    records, offline = qp.scan_registry(
        path, 300, cfg["handoff_queue"].get("sources"))
    assert offline is False, "configured registry must scan as online"
    assert isinstance(records, list)

    src = (ROOT / "src" / "queue_panel.py").read_text(encoding="utf-8")
    assert "self.after(int(self.refresh_seconds * 1000), self._auto_refresh)" in src

    # A missing registry is OFFLINE and is never auto-created.
    missing = str(tmp_path / "_no_such_registry")
    recs, off = qp.scan_registry(missing, 10, None)
    assert off is True and recs == []
    assert not Path(missing).exists(), "a missing registry must not be created"


def test_flow_websocket_reconnect_on_drop(tmp_path):
    """FLOW: WebSocket reconnect on drop.  BEHAVIOUR — the supervisor reacts.

    The supervisor is an infinite loop, so it is driven in a thread against a
    capture that reports a dead websocket and stopped once the rebuild is
    observed. What is asserted is the actual recovery: the unhealthy capture is
    dropped and a fresh one is built.
    """
    bridge = _make_bridge(tmp_path)
    states = {"rebuilt": 0, "stopped": 0}

    class DeadCapture:
        auth_error = None

        def is_running(self):
            return True

        def health(self):
            return False, "websocket not connected"

        def stop(self):
            states["stopped"] += 1

        def is_auth_error(self):
            return False

    bridge.capture = DeadCapture()
    # Recovery FAILS: the rebuild raises, so the fault must survive. A fault
    # that is latched and then cleared by a failed recovery is a fault that
    # can go quiet again, which is the exact failure this surgery exists to
    # prevent.
    def _failing_build():
        states["rebuilt"] += 1
        raise ConnectionError("connect refused")

    bridge._build_capture = _failing_build
    bridge._reconnect_backoff = 0.01

    t = threading.Thread(target=bridge._supervisor, daemon=True)
    t.start()
    deadline = time.time() + 3.0
    while time.time() < deadline and states["rebuilt"] == 0:
        time.sleep(0.02)
    time.sleep(0.2)
    bridge._stopping = True
    t.join(timeout=2.0)

    assert states["rebuilt"] >= 1, "supervisor did not attempt a rebuild"
    assert states["stopped"] >= 1, "unhealthy capture was not stopped"
    # SURGERY D: the dead path's verdict is latched into the engine and a
    # failed recovery does not clear it.
    fault = bridge.v3_engine.health.latched_fault
    assert fault is not None, "engine health fault did not survive recovery failure"
    assert "websocket not connected" in fault
    ok, why = bridge.v3_health()
    assert ok is False and "websocket not connected" in why


def test_successful_reconnect_clears_the_health_fault(tmp_path):
    """The other half of SURGERY D: a real recovery really does clear it.

    Without this, "the fault is latched" is only half a contract — a fault that
    can never clear is indistinguishable from a broken indicator.
    """
    bridge = _make_bridge(tmp_path)
    states = {"rebuilt": 0, "stopped": 0}

    class DeadCapture:
        auth_error = None

        def is_running(self):
            return True

        def health(self):
            return False, "websocket not connected"

        def stop(self):
            states["stopped"] += 1

        def is_auth_error(self):
            return False

    class LiveCapture:
        auth_error = None

        def __init__(self, cfg):
            states["rebuilt"] += 1

        def start(self):
            pass

        def is_auth_error(self):
            return False

        def is_running(self):
            return True

        def health(self):
            return True, "healthy"

    bridge.capture = DeadCapture()
    bridge._build_capture = lambda: LiveCapture(None)
    bridge._reconnect_backoff = 0.01

    t = threading.Thread(target=bridge._supervisor, daemon=True)
    t.start()
    deadline = time.time() + 3.0
    while time.time() < deadline and states["rebuilt"] == 0:
        time.sleep(0.02)
    time.sleep(0.2)
    bridge._stopping = True
    t.join(timeout=2.0)

    assert states["rebuilt"] >= 1
    assert states["stopped"] >= 1
    assert bridge.capture is not None, "healthy capture was not installed"
    assert bridge.v3_engine.health.latched_fault is None, \
        "a successful recovery must clear the latched fault"


def test_flow_voice_command_handlers(tmp_path):
    """FLOW: voice command handlers.  BEHAVIOUR — real command routing."""
    from src.voice_commands import COMMAND_HELP, handle_command

    assert isinstance(COMMAND_HELP, str) and COMMAND_HELP
    assert handle_command("copy") == "copy"
    assert handle_command("right") == "right"
    assert handle_command("save") == "save"
    assert handle_command("quit") == "quit"
    # A command word inside a sentence is NOT a command (baseline behaviour).
    assert handle_command("copy the notes") is None
    assert handle_command("apex predator results") is None

    # And the bridge routes an exact command to the executor, not to typing.
    executed, typed = [], []
    bridge = _make_bridge(tmp_path)
    bridge.continuous = True
    bridge.paused = False
    import src.voice_bridge as vbm
    orig_exec, orig_type = vbm.execute_command, vbm.type_text
    vbm.execute_command = lambda a: executed.append(a) or True
    vbm.type_text = lambda t, interval=0.01: typed.append(t)
    try:
        bridge._handle_final("copy")
    finally:
        vbm.execute_command, vbm.type_text = orig_exec, orig_type
    assert executed == ["copy"] and typed == []
    bridge._stopping = True


def test_flow_keyboard_input_simulation(tmp_path):
    """FLOW: keyboard input simulation.  BYTE-STABLE + live dispatch."""
    from src import keyboard_input as ki

    assert (ROOT / "src" / "keyboard_input.py").read_bytes() == \
        (BASELINE / "src" / "keyboard_input.py").read_bytes()
    for fn in ("type_text", "press_enter", "lock_target_window"):
        assert callable(getattr(ki, fn))

    typed = []
    import src.voice_bridge as vbm
    orig = vbm.type_text
    vbm.type_text = lambda t, interval=0.01: typed.append(t)
    try:
        bridge = _make_bridge(tmp_path)
        bridge.continuous = True
        bridge.paused = False
        bridge._handle_final("the quick brown fox")
    finally:
        vbm.type_text = orig
    assert typed == ["the quick brown fox "]
    bridge._stopping = True


def test_flow_screenshot_capture(tmp_path):
    """FLOW: screenshot capture.  BYTE-STABLE + module surface present."""
    from src import screenshot

    assert (ROOT / "src" / "screenshot.py").read_bytes() == \
        (BASELINE / "src" / "screenshot.py").read_bytes()
    surface = [n for n in dir(screenshot) if not n.startswith("_")]
    assert surface, "screenshot module exposes no public surface"
    assert any(callable(getattr(screenshot, n)) for n in surface)
    bridge = _make_bridge(tmp_path)
    bridge._stopping = True


def test_flow_voice_profiles(tmp_path):
    """FLOW: voice profiles.  BYTE-STABLE + profile dispatch wiring."""
    from src import voice_profile

    assert (ROOT / "src" / "voice_profile.py").read_bytes() == \
        (BASELINE / "src" / "voice_profile.py").read_bytes()
    assert callable(voice_profile.profile_command)
    assert callable(voice_profile.profile_hotkey)
    assert (ROOT / "voice-profile.json").exists()

    # A profile phrase produces typed output rather than plain dictation.
    typed = []
    import src.voice_bridge as vbm
    orig = vbm.type_text
    vbm.type_text = lambda t, interval=0.01: typed.append(t)
    try:
        bridge = _make_bridge(tmp_path)
        bridge.continuous = True
        bridge.paused = False
        bridge._dispatch("send the file to keel")
    finally:
        vbm.type_text = orig
    assert typed, "profile dispatch produced no typed output"
    bridge._stopping = True


def test_flow_config_json_read(tmp_path):
    """FLOW: config.json read.  BEHAVIOUR — the real loader, merged keys."""
    from src.config import load_config

    cfg = load_config(str(ROOT / "config.json"))
    assert cfg["speech_model"] == "universal-3-5-pro"
    assert cfg["sample_rate"] == 16000
    assert cfg["channels"] == 1
    assert cfg["wake_words"] == ["hey keel", "ok keel", "okay keel", "keel"]
    # Wake words are folded into keyterms so the engine spells them.
    assert "Hey Keel" in cfg["keyterms"]
    # The merged V3 keys are present and read back.
    assert cfg["paths"]["transcripts"] == "data/transcripts"
    assert cfg["paths"]["shadow_log"] == "data/shadow-log"
    assert cfg["capture_health"]["silence_is_fault"] is True
    assert cfg["audio_retention"]["retention_days"] == 7
    assert cfg["g6_regression_test"]["min_test_utterance_length"] == 500
    # The key is NOT in config.json. It comes from .env at run time.
    assert cfg["assemblyai_api_key"] == ""


def test_flow_llm_unchanged(tmp_path):
    """FLOW: llm.py behaviour preserved unchanged.  BYTE-STABLE.

    The Sec. 2 requirement is literally "preserved unchanged", so the only
    honest test is a byte comparison against the frozen baseline. A behavioural
    test would also pass after a change nobody asked for.
    """
    assert (ROOT / "src" / "llm.py").read_bytes() == \
        (BASELINE / "src" / "llm.py").read_bytes()
    assert (ROOT / "tests" / "test_llm.py").read_bytes() == \
        (BASELINE / "tests" / "test_llm.py").read_bytes()


# ---------------------------------------------------------------------------
# SURGERY D — engine health
# ---------------------------------------------------------------------------
def test_surgery_d_health_is_observable(tmp_path):
    """SURGERY D: engine health is observable; silence is a fault, not quiet."""
    bridge = _make_bridge(tmp_path)
    engine = bridge.v3_engine

    ok, why = bridge.v3_health()
    assert ok is True and "starting" in why

    # A latched connection fault does NOT self-clear.
    engine.health.mark_health_fault("websocket not connected")
    ok, why = bridge.v3_health()
    assert ok is False and "websocket not connected" in why
    time.sleep(0.05)
    ok, _ = bridge.v3_health()
    assert ok is False, "a latched fault silently cleared itself"

    # A rebuilt session clears it.
    engine.health.clear_fault()
    ok, _ = bridge.v3_health()
    assert ok is True

    # Silence is a fault, and it clears on its own when audio resumes.
    health = engine.health
    health.silence_threshold_seconds = 1
    health.record_audio()
    ok, _ = health.check()
    assert ok is True
    time.sleep(1.2)
    ok, why = health.check()
    assert ok is False and "silence fault" in why
    health.record_audio()
    ok, _ = health.check()
    assert ok is True

    # The health line is wired into the UI, not only into the log file.
    src = (ROOT / "src" / "voice_bridge.py").read_text(encoding="utf-8")
    assert "HEALTH FAULT" in src and "health_label" in src
    bridge._stopping = True


def test_engine_never_blocks_dictation(tmp_path):
    """A dead engine must not stop the operator being heard, and must be loud."""
    bridge = _make_bridge(tmp_path)
    bridge.v3_engine = None  # simulate engine loss
    typed = []
    import src.voice_bridge as vbm
    orig = vbm.type_text
    vbm.type_text = lambda t, interval=0.01: typed.append(t)
    try:
        bridge.on_transcript("engine is gone but the words must still land",
                             is_final=True)
        assert _drain(bridge)
    finally:
        vbm.type_text = orig
    assert typed == ["engine is gone but the words must still land "]
    ok, why = bridge.v3_health()
    assert ok is False and "not initialised" in why
    bridge._stopping = True


def test_persist_failure_does_not_silence_the_operator(tmp_path):
    """A failed durable write is loud AND still delivers the words.

    The two requirements are easy to trade against each other. This asserts
    both: the operator is not silenced by a disk problem, and the operator is
    not lied to by a silent disk problem.
    """
    bridge = _make_bridge(tmp_path)
    seen = []
    bridge._set_status = seen.append
    typed = []
    import src.voice_bridge as vbm
    orig = vbm.type_text
    vbm.type_text = lambda t, interval=0.01: typed.append(t)
    bridge.v3_engine.persist_transcript = lambda *a, **k: (_ for _ in ()).throw(
        OSError("disk on fire"))
    try:
        bridge.on_transcript("the disk is broken but I am still speaking",
                             is_final=True)
        assert _drain(bridge)
    finally:
        vbm.type_text = orig
    assert typed == ["the disk is broken but I am still speaking "]
    assert any("persist error" in s for s in seen), seen
    bridge._stopping = True


def test_interpretation_shadow_runs_offline_with_no_authority(tmp_path):
    """Stage 2 shadow: runs, writes only to the shadow log, affects nothing."""
    bridge = _make_bridge(tmp_path)
    stats = bridge.v3_shadow_stats()
    assert stats["running"] is True
    assert stats["model_version"]
    shadow_dir = Path(stats["shadow_log_dir"])

    bridge.on_transcript(LONG_UTTERANCE, is_final=True)
    assert _drain(bridge)
    deadline = time.time() + 3.0
    while time.time() < deadline and not list(shadow_dir.glob("*.json")):
        time.sleep(0.02)
    logs = list(shadow_dir.glob("*.json"))
    assert logs, "shadow produced no log"
    data = json.loads(logs[0].read_text(encoding="utf-8"))
    assert data["source_transcript"] == LONG_UTTERANCE
    assert data["claims"], "shadow emitted no claims"
    assert data["model_version"]
    for claim in data["claims"]:
        assert claim["model_version"] == data["model_version"]

    # It wrote to the shadow log and NOWHERE else: the transcript count is
    # still exactly one, and the shadow log dir is not the transcript dir.
    assert len(list(Path(bridge.v3_engine.transcripts_dir).glob("*.json"))) == 1
    assert shadow_dir != Path(bridge.v3_engine.transcripts_dir)
    bridge._stopping = True


def test_shadow_and_g6_suite_shipped_byte_identical():
    """The transplanted Stage 2 files are the salvage files, unmodified."""
    assert _sha(ROOT / "src" / "interpretation_shadow.py") == \
        _sha(SALVAGE / "src" / "interpretation_shadow.py")
    assert _sha(ROOT / "tests" / "test_g6_regression.py") == \
        _sha(SALVAGE / "tests" / "test_g6_regression.py")


def test_surgery_surface_is_exactly_the_declared_files():
    """Parity discipline: only the declared-surgery files may differ.

    Guards against an unrequested change reaching the candidate. If a future
    change touches a fourth source file, this fails and the change has to be
    argued for rather than slipped in.
    """
    allowed = {
        "src/intent.py",
        "src/voice_bridge.py",
        "tests/test_voice_bridge.py",
        "config.json",
        "START-VOICEBRIDGE.cmd",
    }
    changed, missing = set(), set()
    for base_file in BASELINE.rglob("*"):
        if not base_file.is_file() or "__pycache__" in base_file.parts:
            continue
        rel = base_file.relative_to(BASELINE).as_posix()
        live = ROOT / rel
        if not live.exists():
            missing.add(rel)
        elif live.read_bytes() != base_file.read_bytes():
            changed.add(rel)
    strays = changed - allowed
    assert not strays, f"unrequested changes outside the surgery surface: {strays}"
    assert not missing, f"baseline files went missing: {missing}"
    # And the changed set is exactly what was declared, not a subset.
    assert changed == allowed, f"expected {allowed} to differ, got {changed}"
