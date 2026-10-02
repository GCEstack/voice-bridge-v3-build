#!/usr/bin/env python3
"""Build gate: no excluded module is present in the V3.1 tree.

The V3.1 order lists hard exclusions, and notes that the V1 config itself
already marks them "LEGACY ARCHITECTURE - do not invest". The point of this
gate is that an exclusion nobody checks is an exclusion that comes back.

    wake-word          dictation hotkey     clipboard watcher
    screenshot         TTS                  src/voice_bridge.py
    queue_local.json   legacy queue state   (model-addressed lanes)

Two kinds of check:
  FILE     an excluded module exists on disk
  CONFIG   an excluded feature is switched on in config.json

    python validation_tools/check_exclusions.py

Exit 0 = clean, 1 = something excluded is present.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

EXCLUDED_FILES = (
    "voice_bridge.py",
    "voice_commands.py",
    "keyboard_input.py",
    "screenshot.py",
    "tts.py",
    "clipboard_watcher.py",
    "queue_local.json",
)

CACHE_DIRS = ("__pycache__",)

EXCLUDED_CONFIG_KEYS = (
    "mode",
    "wake_words",
    "dictation_hotkey",
    "armed_timeout_seconds",
    "clipboard_watcher",
    "screenshot",
    "tts",
    "auto_proofread_after",
    "auto_concise_after",
    "supervisor_interval_seconds",
)

SKIP_DIR_PARTS = (".venv", "venv", ".git", "node_modules", ".pytest_cache")


def walk_files():
    for p in ROOT.rglob("*"):
        if any(part in SKIP_DIR_PARTS for part in p.parts):
            continue
        yield p


def check_files(failures):
    found = []
    for p in walk_files():
        if p.name in EXCLUDED_FILES:
            found.append(p.relative_to(ROOT))
    for f in found:
        failures.append(f"excluded module present: {f}")
    return found


def check_dirs(warnings):
    found = []
    for p in walk_files():
        if p.is_dir() and p.name in CACHE_DIRS:
            found.append(p.relative_to(ROOT))
    return found


def check_pycache(failures):
    found = []
    for p in walk_files():
        if p.suffix == ".pyc" and p.name.split(".")[0] in {
            "voice_bridge", "voice_commands", "screenshot", "tts",
            "clipboard_watcher", "keyboard_input",
        }:
            found.append(p.relative_to(ROOT))
    for f in found:
        failures.append(f"compiled bytecode of an excluded module: {f}")
    return found


def check_config(failures):
    path = ROOT / "config.json"
    if not path.exists():
        failures.append("config.json missing")
        return
    cfg = json.loads(path.read_text(encoding="utf-8"))
    for key in EXCLUDED_CONFIG_KEYS:
        if key in cfg:
            failures.append(f"excluded config key active: {key}")
    blob = json.dumps(cfg).lower()
    for token in ("wake_word", "hey keel", "ok keel", "okay keel"):
        if token in blob:
            failures.append(f"excluded wake-word token in config: {token!r}")


def check_secret(failures):
    """.env must not be in the tree, and config must carry no key."""
    env = ROOT / ".env"
    if env.exists():
        failures.append(".env is present in the tree — the key must never ship")
    gitignore = ROOT / ".gitignore"
    if gitignore.exists():
        txt = gitignore.read_text(encoding="utf-8")
        for required in (".env", "!.env.example"):
            if required not in txt:
                failures.append(f".gitignore missing {required}")
    else:
        failures.append(".gitignore missing")
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    key = (cfg.get("stt", {}) or {}).get("api_key", "")
    if key:
        failures.append("config.json stt.api_key is populated — the key must never ship")


def main() -> int:
    failures: list = []
    warnings: list = []

    check_files(failures)
    check_dirs(warnings)
    check_pycache(failures)
    check_config(failures)
    check_secret(failures)

    print("EXCLUSION SWEEP — VoiceBridge V3.1 Consolidated")
    print("=" * 58)
    print()
    print("  excluded modules : " + ", ".join(EXCLUDED_FILES))
    print("  excluded config  : " + ", ".join(EXCLUDED_CONFIG_KEYS[:6]) + ", ...")
    print()
    print("-" * 58)

    if warnings:
        for w in warnings:
            print(f"[WARN] bytecode cache present (stripped before packaging): {w}")
        print()

    if failures:
        for f in failures:
            print(f"[FAIL] {f}")
        print()
        print(f"[FAIL] {len(failures)} exclusion violation(s)")
        return 1

    print("[PASS] no excluded module file present")
    print("[PASS] no excluded config key active")
    print("[PASS] no wake-word token anywhere in config")
    print("[PASS] no .env in the tree, and config carries no key")
    print("[PASS] no compiled bytecode of a deleted V1 module")
    print()
    print("[PASS] exclusion sweep clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())