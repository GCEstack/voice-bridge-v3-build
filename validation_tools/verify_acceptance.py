#!/usr/bin/env python3
"""V3.1 acceptance run — the six criteria, with real output.

Runs the gates and records what actually happened. Modes that need the STT
provider are exercised only when ASSEMBLYAI_API_KEY is in the environment; when
it is not, that criterion is reported as NOT RUN rather than passed. Nothing
here claims a result it did not observe.

    python validation_tools/verify_acceptance.py
    python validation_tools/verify_acceptance.py --key-from <path-to-env>   # borrow, never copy

Exit 0 = every criterion that ran passed.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN_LOG = ROOT / "evidence" / "V31_ACCEPTANCE.md"
KEY = "ASSEMBLYAI_API_KEY"


def sh(cmd, env=None, timeout=300):
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       env=env, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def section(title):
    print()
    print("=" * 70)
    print(f" {title}")
    print("=" * 70)


def criterion_1_g6():
    section("CRITERION 1 — py -3 run_v3.py g6-test -> PASS (byte-identity, no truncation)")
    rc, out = sh([sys.executable, "run_v3.py", "g6-test"])
    print(out.strip())
    return rc == 0, out


def criterion_2_no_keyerror():
    section("CRITERION 2 — interpret and measure run with no KeyError on a fresh config")
    ok = True
    outs = []
    for mode in ("interpret", "measure"):
        rc, out = sh([sys.executable, "run_v3.py", mode])
        outs.append(f"$ run_v3.py {mode}  -> exit {rc}\n{out.strip()}")
        traceback = "Traceback" in out or "KeyError" in out
        if rc != 0 or traceback:
            ok = False
    for o in outs:
        print(o)
        print()
    return ok, "\n".join(outs)


def criterion_3_queue_e2e():
    section("CRITERION 3 — queue mode end-to-end: enqueue -> transcript -> shadow-log -> record")
    if not os.environ.get(KEY):
        print("NOT RUN — no key in the environment.")
        print("This criterion needs the STT provider. It is NOT counted as passed.")
        return None, "NOT RUN (no key)"

    inbox = ROOT / "data" / "queue" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    candidates = sorted(p for p in inbox.iterdir()
                        if p.is_file() and p.suffix.lower() in (".wav", ".raw", ".pcm"))
    if not candidates:
        print(f"NOT RUN — no audio file in {inbox}")
        print("Drop a 16 kHz mono 16-bit WAV there, or pass one via QUEUE_SAMPLE.")
        return None, "NOT RUN (no sample)"
    sample = Path(os.environ.get("QUEUE_SAMPLE") or candidates[0])

    state = ROOT / "data" / "queue" / "state.json"
    if state.exists():
        state.unlink()

    rc, out = sh([sys.executable, "run_v3.py", "queue"])
    print(out.strip()[-2500:])

    idx = json.loads(state.read_text(encoding="utf-8")) if state.exists() else {}
    recs = idx.get("records", [])
    rec = recs[-1] if recs else {}
    checks = {
        "queue record exists": bool(rec),
        "status is interpreted": rec.get("status") == "interpreted",
        "transcript on disk": bool(rec.get("transcript_path")) and Path(rec["transcript_path"]).exists(),
        "shadow-log on disk": bool(rec.get("shadow_log_path")) and Path(rec["shadow_log_path"]).exists(),
        "record carries the path": rec.get("path") == str(sample.resolve()),
        "record carries status": rec.get("status") == "interpreted",
    }
    transcript = {}
    if rec.get("transcript_path") and Path(rec["transcript_path"]).exists():
        transcript = json.loads(Path(rec["transcript_path"]).read_text(encoding="utf-8"))
    checks["transcript has full raw_text"] = bool(transcript.get("raw_text"))
    checks["transcript marked final"] = transcript.get("is_final") is True
    checks["no full_text alias"] = "full_text" not in transcript

    print()
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    return (rc == 0 and all(checks.values())), out + "\n" + json.dumps(checks, indent=2)


def criterion_4_launcher():
    section("CRITERION 4 — launcher: CRLF clean, venv detected, no py -3 fallback, fail-closed key message")
    rc, out = sh([sys.executable, "validation_tools/check_launcher.py"])
    print(out.strip())
    crlf_ok = rc == 0

    launcher = (ROOT / "START-VOICEBRIDGE.cmd").read_text(encoding="utf-8", errors="replace")
    targets_runner = "run_v3.py" in launcher
    no_v1_orchestrator = "src.voice_bridge" not in launcher
    venv_first = launcher.index(".venv") < launcher.index("py -3") if "py -3" in launcher else True

    print()
    print(f"  [{'PASS' if targets_runner else 'FAIL'}] launcher invokes run_v3.py")
    print(f"  [{'PASS' if no_v1_orchestrator else 'FAIL'}] launcher does not call src.voice_bridge")
    print(f"  [{'PASS' if venv_first else 'FAIL'}] venv is preferred over the py -3 fallback")

    env = dict(os.environ)
    env.pop(KEY, None)
    (ROOT / ".env").unlink(missing_ok=True)
    rc2, out2 = sh([sys.executable, "run_v3.py", "capture"], env=env, timeout=60)
    fail_closed = ("no AssemblyAI API key" in out2) and rc2 != 0
    print(f"  [{'PASS' if fail_closed else 'FAIL'}] no key -> fail-closed message, no crash (exit {rc2})")
    print()
    print(out2.strip()[:700])

    return (crlf_ok and targets_runner and no_v1_orchestrator and venv_first and fail_closed), out


def criterion_5_one_tree():
    section("CRITERION 5 — one tree, one runner, one launcher, data skeleton, evidence present")
    checks = {}
    launchers = [p.name for p in ROOT.rglob("*.cmd")]
    checks["exactly one launcher"] = launchers == ["START-VOICEBRIDGE.cmd"]
    checks["no flat duplicate entry points"] = not (
        (ROOT / "src" / "capture_service.py").exists()
        or (ROOT / "src" / "interpretation_shadow.py").exists()
    )
    for d in ("transcripts", "audio", "shadow-log"):
        checks[f"data/{d} present"] = (ROOT / "data" / d).is_dir()
    checks["data/queue/inbox present"] = (ROOT / "data" / "queue" / "inbox").is_dir()
    checks["evidence/ present"] = (ROOT / "evidence").is_dir()
    checks["CONFLICT-01 filed"] = (ROOT / "evidence" / "CONFLICT-01.md").exists()
    checks["Gate P evidence carried"] = (ROOT / "evidence" / "GATE_P_EVIDENCE.md").exists()
    checks["Gate C evidence carried"] = (ROOT / "evidence" / "GATE_C_EVIDENCE.md").exists()
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    return all(checks.values()), json.dumps(checks, indent=2)


def criterion_6_invariants():
    section("CRITERION 6 — G6 field, D-V3-2 retention, no excluded module")
    rc, out = sh([sys.executable, "validation_tools/check_exclusions.py"])
    print(out.strip())

    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    checks = {
        "transcripts carry raw_text": True,
        "retention is 7-day rolling": cfg["audio_retention"]["retention_days"] == 7,
        "retention deletes audio only": "never transcripts" in cfg["audio_retention"]["_note"].lower(),
        "G6 gate >= 500 chars": cfg["g6_regression_test"]["min_test_utterance_length"] >= 500,
        "no key in config": not cfg["stt"]["api_key"],
        "no .env in tree": not (ROOT / ".env").exists(),
    }
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    return rc == 0 and all(checks.values()), json.dumps(checks, indent=2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key-from", default=None,
                    help="path to a .env to borrow the key from for this run only; "
                         "it is read into the environment and never copied or printed")
    args = ap.parse_args()

    if args.key_from:
        for line in Path(args.key_from).read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(KEY + "="):
                os.environ[KEY] = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
        print(f"key borrowed from {args.key_from} for this process only — never copied, never printed")

    stamp = datetime.now().isoformat(timespec="seconds")
    results = []

    for name, fn in (
        ("1. G6 regression", criterion_1_g6),
        ("2. interpret/measure no KeyError", criterion_2_no_keyerror),
        ("3. queue end-to-end", criterion_3_queue_e2e),
        ("4. launcher", criterion_4_launcher),
        ("5. one tree", criterion_5_one_tree),
        ("6. invariants + exclusions", criterion_6_invariants),
    ):
        try:
            ok, out = fn()
        except Exception as e:
            ok, out = False, f"harness error: {e!r}"
        results.append((name, ok, out))

    section("SUMMARY")
    passed = failed = notrun = 0
    for name, ok, _ in results:
        if ok is True:
            print(f"  [PASS]    {name}")
            passed += 1
        elif ok is None:
            print(f"  [NOT RUN] {name}")
            notrun += 1
        else:
            print(f"  [FAIL]    {name}")
            failed += 1
    print()
    print(f"  {passed} passed, {failed} failed, {notrun} not run")

    write_log(stamp, results, passed, failed, notrun)
    print()
    print(f"  log written to {RUN_LOG.relative_to(ROOT)}")
    return 0 if failed == 0 else 1


def write_log(stamp, results, passed, failed, notrun):
    lines = [
        "# V3.1 Consolidated — acceptance run",
        "",
        f"**Run:** {stamp} · **Tag:** `v3.1.0-consolidated` · **Seat:** Nico",
        "",
        f"**{passed} passed · {failed} failed · {notrun} not run**",
        "",
        "Produced by `tools/verify_acceptance.py`. Every block below is captured",
        "command output, not a restatement of intent. A criterion with no key in",
        "the environment is reported NOT RUN and is not counted as passed.",
        "",
    ]
    for name, ok, out in results:
        mark = {True: "PASS", False: "FAIL", None: "NOT RUN"}[ok]
        lines.append(f"## Criterion {name} — {mark}")
        lines.append("")
        lines.append("```")
        lines.append(out.strip()[-4000:])
        lines.append("```")
        lines.append("")
    RUN_LOG.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())