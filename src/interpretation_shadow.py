#!/usr/bin/env python3
"""
interpretation_shadow.py — V3 Interpretation Shadow Pipeline (V-GATE 1)

Stage 2 only: speech-act classification + slots + multi-claim output + per-claim
confidence. Model version recorded on every claim.

Runs OFFLINE over captured transcripts. No authority. Emits interpretation claims
to a SHADOW LOG (not the ledger — V-GATE 2 territory).

Key constraints:
- Output goes to data/shadow-log/ ONLY
- Never writes to the ledger
- Model version recorded on every claim
- Reference candidates unresolved at V1
- Runs WHILE corpus accumulates (concurrent, not sequential)
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("v3.interpretation")


class SpeechActType(Enum):
    QUESTION = "question"
    STATEMENT = "statement"
    COMMAND = "command"
    REQUEST = "request"
    PROMISE = "promise"
    ACKNOWLEDGMENT = "acknowledgment"
    FRUSTRATION = "frustration"
    PRAISE = "praise"
    UNKNOWN = "unknown"


@dataclass
class Claim:
    claim_id: str
    speech_act: SpeechActType
    slots: dict
    text: str
    confidence: float
    model_version: str
    reference_candidates: list = field(default_factory=list)


@dataclass
class InterpretationResult:
    event_id: str
    timestamp: str
    source_transcript: str
    claims: list
    model_version: str
    processing_time_ms: float
    corpus_volume_note: Optional[str] = None


class InterpretationShadowPipeline:
    def __init__(self, shadow_log_dir: str, model_version: str = "gpt-4o-mini"):
        self.shadow_log_dir = Path(shadow_log_dir)
        self.shadow_log_dir.mkdir(parents=True, exist_ok=True)
        self.model_version = model_version
        self._running = False

    def interpret(self, transcript: str, event_id: str) -> InterpretationResult:
        start = time.perf_counter()
        claims = self._classify_speech_acts(transcript)
        processing_time_ms = (time.perf_counter() - start) * 1000

        result = InterpretationResult(
            event_id=event_id,
            timestamp=datetime.now().isoformat(timespec="milliseconds"),
            source_transcript=transcript,
            claims=claims,
            model_version=self.model_version,
            processing_time_ms=processing_time_ms
        )

        self._persist_shadow_log(result)
        return result

    def _classify_speech_acts(self, text: str) -> list[Claim]:
        claims = []
        text_lower = text.lower().strip()

        first_word = text_lower.split()[0] if text_lower.split() else ""

        if text_lower.endswith("?") or first_word in ("what", "how", "when", "where", "why", "who", "can", "do", "does", "is", "are", "will", "should"):
            speech_act = SpeechActType.QUESTION
            confidence = 0.85
        elif first_word in ("do", "go", "run", "start", "stop", "get", "make", "build", "create", "delete", "remove"):
            speech_act = SpeechActType.COMMAND
            confidence = 0.80
        elif any(p in text_lower for p in ("good job", "great job", "perfect", "amazing", "awesome", "nice", "love it")):
            speech_act = SpeechActType.PRAISE
            confidence = 0.90
        elif any(f in text_lower for f in ("what the fuck", "are you serious", "this is a mess", "you broke it", "damn it", "for the love of god")):
            speech_act = SpeechActType.FRUSTRATION
            confidence = 0.88
        elif any(a in text_lower for a in ("got it", "okay", "ok", "good", "fine", "understood", "capiche", "right", "gotcha")):
            speech_act = SpeechActType.ACKNOWLEDGMENT
            confidence = 0.92
        elif any(p in text_lower for p in ("i'll", "i will", "i promise", "i'll get", "i'll do")):
            speech_act = SpeechActType.PROMISE
            confidence = 0.75
        elif first_word in ("hey", "so", "listen", "look"):
            speech_act = SpeechActType.STATEMENT
            confidence = 0.70
        else:
            speech_act = SpeechActType.STATEMENT
            confidence = 0.65

        claim = Claim(
            claim_id=str(uuid.uuid4()),
            speech_act=speech_act,
            slots=self._extract_slots(text),
            text=text,
            confidence=confidence,
            model_version=self.model_version,
            reference_candidates=[]
        )
        claims.append(claim)

        if len(text) > 200 and len(text.split(",")) > 2:
            sentences = text.replace(",", ".").split(".")
            for i, sent in enumerate(sentences):
                if sent.strip() and i > 0:
                    sub_claim = Claim(
                        claim_id=str(uuid.uuid4()),
                        speech_act=SpeechActType.STATEMENT,
                        slots={},
                        text=sent.strip(),
                        confidence=confidence * 0.8,
                        model_version=self.model_version,
                        reference_candidates=[]
                    )
                    claims.append(sub_claim)

        return claims

    def _extract_slots(self, text: str) -> dict:
        slots = {}
        text_lower = text.lower()

        if any(w in text_lower for w in ("file", "folder", "directory", "path")):
            slots["has_file_reference"] = True
        if any(w in text_lower for w in ("project", "app", "system")):
            slots["has_project_reference"] = True
        if any(w in text_lower for w in ("test", "verify", "check", "validate")):
            slots["has_action_test"] = True
        if any(w in text_lower for w in ("build", "create", "make", "implement")):
            slots["has_action_build"] = True

        words = text_lower.split()
        for word in words:
            if word.startswith("@") or (word[0].isupper() and len(word) > 1 and word not in ("I", "I'll", "I'm", "I've", "Don't", "Can't", "Won't")):
                if "mentions" not in slots:
                    slots["mentions"] = []
                slots["mentions"].append(word)

        return slots

    def _persist_shadow_log(self, result: InterpretationResult) -> None:
        filename = f"{result.event_id}.json"
        path = self.shadow_log_dir / filename

        data = {
            "event_id": result.event_id,
            "timestamp": result.timestamp,
            "source_transcript": result.source_transcript,
            "claims": [
                {
                    "claim_id": c.claim_id,
                    "speech_act": c.speech_act.value,
                    "slots": c.slots,
                    "text": c.text,
                    "confidence": c.confidence,
                    "model_version": c.model_version,
                    "reference_candidates": c.reference_candidates
                }
                for c in result.claims
            ],
            "model_version": result.model_version,
            "processing_time_ms": result.processing_time_ms,
            "corpus_volume_note": result.corpus_volume_note
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"Shadow log written: {result.event_id} ({len(result.claims)} claims)")


def run_interpretation_shadow(
    transcripts_dir: str,
    shadow_log_dir: str,
    model_version: str = "gpt-4o-mini"
) -> list[InterpretationResult]:
    pipeline = InterpretationShadowPipeline(shadow_log_dir, model_version)
    results = []

    transcripts_path = Path(transcripts_dir)
    if not transcripts_path.exists():
        logger.warning(f"Transcripts dir not found: {transcripts_dir}")
        return results

    for transcript_file in sorted(transcripts_path.glob("*.json")):
        try:
            with open(transcript_file, encoding="utf-8") as f:
                data = json.load(f)

            event_id = data.get("event_id", transcript_file.stem)
            raw_text = data.get("raw_text", "")

            if not raw_text:
                continue

            result = pipeline.interpret(raw_text, event_id)
            results.append(result)

        except Exception as e:
            logger.error(f"Failed to interpret {transcript_file}: {e}")

    return results


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    transcripts_dir = "data/transcripts"
    shadow_log_dir = "data/shadow-log"

    if len(sys.argv) > 1:
        transcripts_dir = sys.argv[1]
    if len(sys.argv) > 2:
        shadow_log_dir = sys.argv[2]

    results = run_interpretation_shadow(transcripts_dir, shadow_log_dir)
    print(f"Interpretation complete: {len(results)} transcripts processed")