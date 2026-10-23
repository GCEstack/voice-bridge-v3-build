"""Headless tests for the handoff review panel (registry read + reviewer state).

No Tkinter root is created here — only the pure helpers are exercised.
"""

import json
from pathlib import Path

import src.queue_panel as qp
from src.queue_panel import (
    normalize_record,
    open_artifact,
    record_text,
)

ROOT = Path(__file__).resolve().parents[1]


def test_normalize_rejects_non_object():
    try:
        normalize_record([1, 2], Path("/tmp/x.json"))
    except ValueError:
        pass
    else:
        raise AssertionError("non-object record must be rejected")


def test_normalize_degrades_legacy_and_missing_subject(tmp_path):
    legacy = normalize_record(
        {"source": "peter", "subject": "memo", "state": "completed",
         "created_at": "2026-08-30T11:00:00"},
        tmp_path / "legacy.json")
    assert legacy["source"] == "peter"
    assert legacy["subject"] == "memo"
    assert legacy["state"] == "completed"

    no_subject = normalize_record(
        {"artifact": r"C:\tmp\the-thing.md"}, tmp_path / "ns.json")
    assert no_subject["subject"] == "the-thing"
    assert no_subject["state"] == "-"
    assert no_subject["source"] == "?"


def test_record_text_render():
    txt = record_text({"id": "h-9", "project": "P", "workstream": "W",
                       "source": "Nico", "artifact": r"C:\a\b.py",
                       "created_at": "2026-09-26T10:00:00",
                       "subject": "s", "state": "completed"})
    assert "id: h-9" in txt
    assert "source: Nico" in txt
    assert "artifact: C:\\a\\b.py" in txt


def test_open_artifact_never_opens_missing_or_url():
    ok, msg = open_artifact("")
    assert not ok and "no local artifact" in msg
    ok, msg = open_artifact(r"C:\definitely\not\here.txt")
    assert not ok and "not found" in msg


def test_old_legacy_helpers_are_gone():
    for gone in ("scan_registry", "load_dismissed", "save_dismissed",
                 "visible", "tag_for"):
        assert not hasattr(qp, gone), f"{gone} must not exist in new queue panel"