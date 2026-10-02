"""Headless tests for the handoff review panel (registry read + reviewer state).

No Tkinter root is created here — only the pure helpers are exercised.
"""

import json
from pathlib import Path

import src.queue_panel as qp
from src.queue_panel import (
    load_dismissed,
    normalize_record,
    open_artifact,
    record_text,
    save_dismissed,
    scan_registry,
    tag_for,
    visible,
)

ROOT = Path(__file__).resolve().parents[1]


# -- registry scan ------------------------------------------------------
def test_scan_registry_reads_contract_fields(tmp_path):
    d = tmp_path / "queue"
    d.mkdir()
    (d / "h-1.json").write_text(json.dumps({
        "id": "h-1", "project": "VoiceBridge", "workstream": "Handoff Review",
        "from": "Nico", "to": "Coda", "status": "ready", "source_type": "code",
        "local_path": str(tmp_path / "a.py"), "drive_file_id": "1AbC",
        "created_at": "2026-09-26T10:15:00", "subject": "panel built",
        "body": "read-only surface",
    }), encoding="utf-8")
    (d / "h-2.json").write_text(json.dumps({
        "id": "h-2", "project": "EC8", "workstream": "Parent Quant",
        "from": "Luce", "to": "Don", "status": "blocked", "source_type": "evidence",
        "local_path": "", "drive_file_id": None,
        "created_at": "2026-09-26T11:00:00", "subject": "gate closed",
        "body": "waiting",
    }), encoding="utf-8")

    items, offline = scan_registry(str(d))
    assert offline is False
    assert [i["id"] for i in items] == ["h-2", "h-1"]      # newest first
    first = items[1]
    assert first["project"] == "VoiceBridge"
    assert first["workstream"] == "Handoff Review"
    assert first["from"] == "Nico"
    assert first["to"] == "Coda"
    assert first["status"] == "ready"
    assert first["source_type"] == "code"
    assert first["drive_file_id"] == "1AbC"
    assert first["local_path"].endswith("a.py")
    assert first["body"] == "read-only surface"
    assert items[0]["drive_file_id"] == ""


def test_scan_registry_missing_folder_is_offline_and_never_created(tmp_path):
    ghost = tmp_path / "does-not-exist"
    items, offline = scan_registry(str(ghost))
    assert items == [] and offline is True
    assert not ghost.exists()
    assert scan_registry("", 10) == ([], True)
    assert scan_registry("   ", 10) == ([], True)


def test_scan_registry_skips_malformed_file(tmp_path):
    d = tmp_path / "queue"
    d.mkdir()
    (d / "bad.json").write_text("{not json at all", encoding="utf-8")
    (d / "list.json").write_text("[1,2,3]", encoding="utf-8")
    (d / "good.json").write_text(json.dumps({"id": "ok", "subject": "s"}),
                                 encoding="utf-8")
    items, offline = scan_registry(str(d))
    assert offline is False
    assert [i["id"] for i in items] == ["ok"]


def test_scan_registry_caps_and_sorts(tmp_path):
    d = tmp_path / "queue"
    d.mkdir()
    for n in range(5):
        (d / f"r{n}.json").write_text(json.dumps({
            "id": f"r{n}", "subject": f"s{n}",
            "created_at": f"2026-09-26T09:0{n}:00"}), encoding="utf-8")
    items, offline = scan_registry(str(d), limit=2)
    assert offline is False
    assert [i["id"] for i in items] == ["r4", "r3"]


def test_normalize_degrades_legacy_and_missing_subject(tmp_path):
    legacy = normalize_record(
        {"from": "peter", "subject": "memo", "body": "x", "status": "pending",
         "created_at": "2026-08-30T11:00:00"},
        tmp_path / "legacy.json")
    assert legacy["project"] == "-"
    assert legacy["workstream"] == "-"
    assert legacy["source_type"] == "-"
    assert legacy["local_path"] == ""
    assert legacy["status"] == "pending"
    assert legacy["body"] == "x"

    no_subject = normalize_record(
        {"local_path": r"C:\tmp\the-thing.md"}, tmp_path / "ns.json")
    assert no_subject["subject"] == "the-thing"
    assert no_subject["status"] == "ready"
    assert no_subject["from"] == "?"


def test_normalize_rejects_non_object():
    try:
        normalize_record([1, 2], Path("/tmp/x.json"))
    except ValueError:
        pass
    else:
        raise AssertionError("non-object record must be rejected")


# -- reviewer state -----------------------------------------------------
def test_visible_hides_dismissed_unless_toggled():
    items = [{"id": "a"}, {"id": "b"}]
    assert visible(items, set()) == items
    assert visible(items, {"a"}) == [{"id": "b"}]
    assert visible(items, {"a"}, show_dismissed=True) == items


def test_load_save_dismissed_roundtrip(tmp_path):
    p = str(tmp_path / "state.json")
    assert load_dismissed(p) == set()
    assert save_dismissed(p, {"h-2", "h-1"}) is True
    assert load_dismissed(p) == {"h-1", "h-2"}
    assert save_dismissed("", {"x"}) is False


def test_load_dismissed_tolerates_corrupt_and_legacy_shapes(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{{{", encoding="utf-8")
    assert load_dismissed(str(bad)) == set()
    lst = tmp_path / "list.json"
    lst.write_text(json.dumps(["a", "b"]), encoding="utf-8")
    assert load_dismissed(str(lst)) == {"a", "b"}
    empty = tmp_path / "void.json"
    empty.write_text(json.dumps({"schema": "x"}), encoding="utf-8")
    assert load_dismissed(str(empty)) == set()


def test_local_state_file_is_never_inside_the_registry(tmp_path):
    registry = tmp_path / "queue"
    registry.mkdir()
    state = tmp_path / "queue_local.json"
    assert state.parent != registry


# -- actions ------------------------------------------------------------
def test_record_text_render():
    txt = record_text({"id": "h-9", "project": "P", "workstream": "W",
                       "from": "Nico", "to": "Coda", "status": "ready",
                       "source_type": "code", "local_path": r"C:\a\b.py",
                       "drive_file_id": "", "created_at": "2026-09-26T10:00:00",
                       "subject": "s", "body": "the body"})
    for token in ("id: h-9", "project: P", "workstream: W", "from: Nico",
                  "to: Coda", "status: ready", r"local_path: C:\a\b.py",
                  "drive_file_id: -", "the body"):
        assert token in txt
    assert "(no body)" in record_text({"id": "x"})


def test_open_artifact_never_opens_missing_or_url():
    ok, msg = open_artifact("")
    assert not ok and "no local artifact" in msg
    ok, msg = open_artifact(r"C:\definitely\not\here.txt")
    assert not ok and "not found" in msg


def test_tag_for_colours():
    assert tag_for("ready", False) == "ready"
    assert tag_for("pending", False) == "ready"
    assert tag_for("reviewed", False) == "reviewed"
    assert tag_for("done", False) == "reviewed"
    assert tag_for("blocked", False) == "blocked"
    assert tag_for("ready", True) == "dismissed"


# -- removed by strategy E ---------------------------------------------
def test_route_and_intake_crawl_are_gone():
    for gone in ("route_note", "scan_sources", "scan_source", "slugify",
                 "_stamp", "_rand4"):
        assert not hasattr(qp, gone), f"{gone} must not be revived"


def test_config_carries_handoff_queue_and_dropped_intake_keys():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    assert "handoff_queue" in cfg
    hq = cfg["handoff_queue"]
    assert hq["registry_path"].endswith("queue")
    assert Path(hq["registry_path"]).drive              # absolute, has a drive
    assert hq["local_state"].endswith("queue_local.json")
    for dropped in ("queue_sources", "route_buttons", "queue_refresh_seconds"):
        assert dropped not in cfg, f"{dropped} must be gone"
