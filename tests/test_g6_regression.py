#!/usr/bin/env python3
"""
test_g6_regression.py — G6 Full-Fidelity Regression Test (V-GATE 1)

Regression test: capture a >500-char utterance; durable transcript on disk
is byte-identical to STT output.

This test ships with V-GATE 1.
"""

import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from capture_service import CaptureService, CaptureConfig


def test_g6_full_fidelity_transcript():
    test_transcript = (
        "This is a test utterance that is designed to be longer than five hundred characters "
        "so that we can verify that the full-fidelity transcript persistence is working correctly. "
        "The old system would truncate this to eighty characters at the logging boundary in intent.py line one hundred and two. "
        "We are now ensuring that the complete STT output is preserved before any normalization, intent classification, or lossy transform. "
        "This is the G6 invariant that must be maintained throughout the VoiceBridge V3 system. "
        "Any component that receives full text and persists less than the full text is a defect, not a design choice."
    )

    assert len(test_transcript) > 500, f"Test transcript must be >500 chars, got {len(test_transcript)}"

    with tempfile.TemporaryDirectory() as tmpdir:
        transcripts_dir = os.path.join(tmpdir, "transcripts")
        audio_dir = os.path.join(tmpdir, "audio")

        config = CaptureConfig(
            api_key="test-key",
            transcripts_dir=transcripts_dir,
            audio_dir=audio_dir
        )

        service = CaptureService(config)

        record = service.persist_transcript(test_transcript, is_partial=False)

        loaded_path = Path(transcripts_dir) / f"{record.event_id}.json"
        assert loaded_path.exists(), f"Transcript file not created: {loaded_path}"

        with open(loaded_path, encoding="utf-8") as f:
            loaded_data = json.load(f)

        loaded_text = loaded_data.get("raw_text", "")

        assert loaded_text == test_transcript, (
            f"G6 VIOLATION: durable transcript is NOT byte-identical to STT output.\n"
            f"Expected length: {len(test_transcript)}\n"
            f"Loaded length: {len(loaded_text)}\n"
            f"Expected: {test_transcript[:100]}...\n"
            f"Loaded: {loaded_text[:100]}..."
        )

        print(f"[PASS] G6 regression test: {len(test_transcript)} chars persisted byte-identical")
        return True


def test_ui_preview_may_shorten():
    test_transcript = (
        "This is a longer test transcript that is definitely going to be more than five hundred characters "
        "because we need to verify that the UI preview can shorten while the durable source never shortens. "
        "The system is designed to allow the display layer to truncate for UI purposes but the persistent "
        "storage must always contain the full original text from the STT boundary. This is the second test "
        "case for the G6 invariant verification and it must also exceed five hundred characters in length. "
        "This additional text ensures we have sufficient characters to meet the five hundred character minimum."
    )

    assert len(test_transcript) > 500, f"Test transcript must be >500 chars, got {len(test_transcript)}"

    with tempfile.TemporaryDirectory() as tmpdir:
        transcripts_dir = os.path.join(tmpdir, "transcripts")
        audio_dir = os.path.join(tmpdir, "audio")

        config = CaptureConfig(
            api_key="test-key",
            transcripts_dir=transcripts_dir,
            audio_dir=audio_dir
        )

        service = CaptureService(config)
        record = service.persist_transcript(test_transcript, is_partial=False)

        loaded_path = Path(transcripts_dir) / f"{record.event_id}.json"
        with open(loaded_path, encoding="utf-8") as f:
            loaded_data = json.load(f)

        durable_text = loaded_data["raw_text"]

        ui_preview = durable_text[:80]

        assert durable_text == test_transcript, "Durable source must NOT be shortened"

        print(f"[PASS] UI preview may shorten (80 chars): '{ui_preview}'")
        print(f"[PASS] Durable source preserved ({len(durable_text)} chars)")
        return True


if __name__ == "__main__":
    print("=" * 60)
    print("G6 FULL-FIDELITY REGRESSION TESTS")
    print("=" * 60)

    test_g6_full_fidelity_transcript()
    test_ui_preview_may_shorten()

    print("=" * 60)
    print("ALL G6 TESTS PASSED")
    print("=" * 60)