"""intent.py — classify an utterance's intent + cadence for the audit.

Reads past profanity and repetition to capture the Don's actual intent, so the
audit knows what he means, not just what he said. Mirrors the intent phrases in
.kimi-code/AGENTS.md.
"""

from __future__ import annotations

import datetime
import os

PRAISE = (
    "good job", "great job", "good fucking job", "great fucking job", "amazing",
    "awesome", "killed it", "perfect", "bellissima", "va bene", "tutto bene",
    "you the man", "nice", "love it", "that's the one", "on point", "nailed it",
)
FRUSTRATION = (
    "what the fuck", "are you serious", "this is a mess", "why would you",
    "you broke it", "that's wrong", "not again", "you're kidding", "damn it",
    "for the love of god",
)
EXECUTE = ("get it done", "do it now", "just do it", "go get it", "execute", "run it")
THINK = ("think on it", "hold on", "reflect on", "sit on it")
DISCUSS = ("let's discuss", "stop everything", "let's talk")
ACKNOWLEDGE = (
    "got it", "okay", "ok", "capiche", "capeesh", "kapish", "good", "fine",
    "understood", "right", "gotcha",
)
FILLERS = ("you know", "um", "uh", "like", "basically", "so basically")

def _count_repetition(tokens):
    counts = {}
    for w in tokens:
        counts[w] = counts.get(w, 0) + 1
    reps = [w for w, c in counts.items() if c >= 3]
    return reps

def classify(text: str):
    """Return (intent, cadence) where cadence is a dict of markers."""
    low = text.lower().strip()
    tokens = low.split()
    cadence = {
        "words": len(tokens),
        "has_profanity": any(w in low for w in ("fuck", "shit", "damn", "hell")),
        "repetition": _count_repetition(tokens),
        "fillers": [f for f in FILLERS if f in low],
    }

    # Score-based, order matters: praise/anger over commands when both present.
    intent = "NEUTRAL"
    if any(p in low for p in PRAISE):
        intent = "PRAISE"
    elif any(f in low for f in FRUSTRATION):
        intent = "FRUSTRATION"
    elif any(d in low for d in DISCUSS):
        intent = "DISCUSS"
    elif any(t in low for t in THINK):
        intent = "THINK"
    elif any(e in low for e in EXECUTE):
        intent = "EXECUTE"
    elif any(a in low for a in ACKNOWLEDGE):
        intent = "ACKNOWLEDGE"
    elif low.endswith("?") or any(w in ("why", "what", "how", "when", "where", "who", "is", "are", "can", "do", "did") for w in tokens[:2]):
        intent = "QUESTION"

    cadence["intent"] = intent
    return intent, cadence


_LOG_MAX_BYTES = 1_000_000
_KEEP_BACKUPS = 2


def _rotate_if_large(path):
    """Roll intent_audit.log when it crosses the cap (bounded disk growth)."""
    try:
        if not os.path.exists(path):
            return
        if os.path.getsize(path) < _LOG_MAX_BYTES:
            return
        for i in range(_KEEP_BACKUPS, 0, -1):  # .2 -> .1, shift down, drop oldest
            src = f"{path}.{i - 1}" if i > 1 else path
            dst = f"{path}.{i}"
            if os.path.exists(src):
                if os.path.exists(dst):
                    os.remove(dst)
                os.rename(src, dst)
    except Exception:
        pass


def log_utterance(text: str, path=None, preview_chars: int = 0):
    """Append one audited utterance (intent + cadence) to intent_audit.log.

    V3 / G6 — THE 80-CHARACTER TRUNCATION IS GONE (2026-10-01, VoiceBridge V3
    integrated build, STEP 3.A).

    Baseline behaviour (the defect this build exists to kill): the audited text
    was written as `text[:80]`, so a 600-character utterance produced an audit
    line that silently lied about what was said. Two independent losses came
    from that one bound — the durable audit lost the tail, and the loss was
    invisible, because a truncated line looks exactly like a complete one.

    Now the FULL transcript is written. Nothing is shortened at this boundary.
    The durable transcript of record is `data/transcripts/<event_id>.json`
    (src/capture_service.py); this log is the intent/cadence view of the same
    text, so it carries the same text, not a digest of it.

    `preview_chars` is an EXPLICIT, opt-in, caller-declared preview bound for a
    display surface. It defaults to 0 = never shorten, so no caller can
    reintroduce the baseline defect by accident. A shortened preview is
    labelled `[TRUNCATED FOR PREVIEW]` in the line itself, so a reader can
    never mistake a preview for the record.

    Consequences, all intended:
      * Log lines are now as long as the utterance. Rotation below is the
        bound on growth, not a character cap.
      * Anything that parses this file must tolerate long lines. `report()`
        already reads line-wise, so it is unaffected.
    """
    intent, cadence = classify(text)
    if not path:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "intent_audit.log")
    shown = text if not preview_chars else text[:preview_chars]
    line = (
        f"[{datetime.datetime.now().isoformat(timespec='seconds')}] "
        f"{intent:12} | words={cadence['words']} | profanity={cadence['has_profanity']} "
        f"| reps={cadence['repetition'] or '-'} | fillers={cadence['fillers'] or '-'} "
        f"| '{shown}'"
        f"{' [TRUNCATED FOR PREVIEW]' if preview_chars and len(text) > preview_chars else ''}"
    )
    _rotate_if_large(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return intent, cadence


def report(path=None):
    """Summarize intent_audit.log into an audit report."""
    if not path:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "intent_audit.log")
    if not os.path.exists(path):
        return "no intent_audit.log yet"
    import collections
    counts = collections.Counter()
    prof = 0
    total = 0
    examples = collections.defaultdict(list)
    for ln in open(path, encoding="utf-8"):
        total += 1
        parts = ln.split(" | ")
        intent = parts[0].split("] ")[-1].strip()
        counts[intent] += 1
        if "profanity=True" in ln:
            prof += 1
        if len(examples[intent]) < 2:
            # report() is a DISPLAY surface, so it may shorten — but it labels
            # the shortening, so a preview is never read as the record.
            ex = ln.split("| '")[-1].rstrip("'\n")
            ex = ex.replace(" [TRUNCATED FOR PREVIEW]", "")
            if len(ex) > 80:
                ex = ex[:80] + f"... [+{len(ex) - 80} more chars]"
            examples[intent].append(ex)
    out = [f"INTENT/CADENCE AUDIT — {total} utterances", "-" * 40]
    for intent, n in counts.most_common():
        out.append(f"  {intent:12} {n}")
    out.append(f"  profanity-as-emphasis: {prof}")
    out.append("")
    for intent, exs in examples.items():
        for e in exs:
            out.append(f"  [{intent}] {e}")
    return "\n".join(out)