"""Completion artifact contract — the ONE way a model returns meaningful work.

Design rule (Don, 2026-10-03): the artifact must be understandable on its own,
with no routing machinery, no seat lifecycle and no handoff taxonomy around it.

REQUIRED
    id          str   stable identity for this piece of work
    created_at  str   ISO-8601, when the work was completed
    source      str   who produced it (a seat name, or a free-text producer)
    subject     str   one line: what happened, in Don's reading terms
    artifact    str   path to the result itself
    state       str   the outcome of the work (see RESULT_STATES)

OPTIONAL — genuinely optional. Absence is never a reason to reject or hide.
    project     str
    workstream  str

DELIBERATELY ABSENT
    from / to            no seat-to-seat routing
    route_type           no route classification
    routing_status       no routing disposition
    gate                 no gate vocabulary
    next_route           no mandatory successor
    drive_file_id        no transport correlation
    status               no seat lifecycle states

``state`` describes THE WORK, not the queue. Queue membership is expressed by
where the file lives (queue/ = active, archive/ = archived), never by a field,
so nothing can be hidden by claiming a state.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

SCHEMA = "gce.completion.artifact"
SCHEMA_VERSION = "1.0"

REQUIRED_FIELDS = ("id", "created_at", "source", "subject", "artifact", "state")
OPTIONAL_FIELDS = ("project", "workstream")

# Free-form outcome vocabulary. Documented, not enforced as an enum: an unknown
# value is reported but still accepted, because rejecting real work over a label
# is the failure mode this whole reset exists to remove.
RESULT_STATES = ("completed", "partial", "failed", "blocked")

_ID_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class ContractError(ValueError):
    """The artifact does not satisfy the contract. Message is operator-facing."""


def safe_name(raw_id: str) -> str:
    """Filesystem-safe, collision-resistant file stem for an id.

    The sanitized id alone is not enough: 'A/B' and 'A:B' both collapse to 'A-B'.
    A digest of the RAW id is appended so two distinct ids can never fight over
    one file.
    """
    raw = str(raw_id)
    stem = _ID_SAFE.sub("-", raw).strip("-")[:80] or "item"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    return f"{stem}-{digest}"


def content_key(source: str, subject: str, artifact: str) -> str:
    """Dedup key independent of the chosen id.

    Two different ids describing the same completed work must not both enter the
    queue. Keyed on the work itself, not on the label.
    """
    basis = f"{source}|{subject}|{artifact}".strip().lower()
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def validate(raw: dict) -> dict:
    """Return a normalized artifact dict, or raise ContractError naming the fault.

    Optional metadata is carried through untouched. Missing optional metadata is
    never an error and never suppresses visibility.
    """
    if not isinstance(raw, dict):
        raise ContractError("artifact is not a JSON object")

    unknown = [k for k in raw if k not in REQUIRED_FIELDS + OPTIONAL_FIELDS]
    # Unknown keys are reported by the caller, not rejected: a model that adds a
    # note must not have its work silently refused.

    missing = [f for f in REQUIRED_FIELDS if raw.get(f) in (None, "", [])]
    if missing:
        raise ContractError("missing required field(s): " + ", ".join(missing))

    item = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "id": str(raw["id"]).strip(),
        "created_at": str(raw["created_at"]).strip(),
        "source": str(raw["source"]).strip(),
        "subject": str(raw["subject"]).strip(),
        "artifact": str(raw["artifact"]).strip(),
        "state": str(raw["state"]).strip(),
    }
    for opt in OPTIONAL_FIELDS:
        val = raw.get(opt)
        if val not in (None, ""):
            item[opt] = str(val).strip()

    item["content_key"] = content_key(item["source"], item["subject"], item["artifact"])
    return item


def read(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise ContractError(f"artifact file not found: {p}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ContractError(f"artifact is not valid JSON ({p}): {e}") from e
    item = validate(raw)
    item["_source_file"] = str(p)
    return item


def write(path: str | Path, item: dict) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(item, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def describe(item: dict) -> str:
    """One-line human summary used in logs, CLI output and handoff payloads."""
    tag = f"[{item.get('state', '?')}]"
    proj = f" {item.get('project')}" if item.get("project") else ""
    return f"{tag} {item.get('source', '?')} -> {item.get('subject', '?')}{proj}"