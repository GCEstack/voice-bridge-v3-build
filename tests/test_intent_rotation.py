"""intent_audit.log rotation tests (bounded disk growth)."""

import os
import tempfile
from unittest.mock import patch

from src.intent import log_utterance, report, _rotate_if_large


def _fake_text(n: int) -> str:
    return ("freddy " * (n // 7 + 1))[:n]


def test_log_rotation_keeps_bounded_backups(tmp_path):
    path = str(tmp_path / "intent_audit.log")
    # Write a lot of utterances with a tiny cap: rotation must keep at most
    # _KEEP_BACKUPS backup files and a small active file (bounded growth).
    with patch("src.intent._LOG_MAX_BYTES", 2048), \
         patch("src.intent._KEEP_BACKUPS", 2):
        for _ in range(400):
            log_utterance(_fake_text(40), path=path)
    backups = sorted(
        p for p in os.listdir(tmp_path)
        if p.startswith("intent_audit.log") and p != "intent_audit.log"
    )
    assert len(backups) <= 2
    assert os.path.exists(path)
    assert os.path.getsize(path) <= 4096


def test_rotate_if_large_does_nothing_when_small(tmp_path):
    path = str(tmp_path / "x.log")
    with open(path, "w", encoding="utf-8") as f:
        f.write("small")
    with patch("src.intent._LOG_MAX_BYTES", 1000):
        _rotate_if_large(path)
    assert os.path.exists(path)
    assert not os.path.exists(path + ".1")


def test_report_still_works_after_rotation(tmp_path):
    path = str(tmp_path / "intent_audit.log")
    log_utterance("get it done", path=path)
    out = report(path=path)
    assert "utterances" in out
    assert "EXECUTE" in out


def test_log_utterance_returns_classification(tmp_path):
    path = str(tmp_path / "intent_audit.log")
    intent, cadence = log_utterance("you broke it", path=path)
    assert intent == "FRUSTRATION"
    assert cadence["has_profanity"] is False