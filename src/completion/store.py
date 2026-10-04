"""Queue store — the ONE place the live VoiceBridge queue is read and written.

Layout, all inside the live product tree:

    <root>/queue/<id>.json          ACTIVE items. Don has not acted on these.
    <root>/archive/items/<id>.json  ARCHIVED items. Source of record, kept.
    <root>/archive/handoffs/<id>.md HANDOFF payloads produced from the queue.
    <root>/state/archive_ledger.json Durable record of every archive event.
    <root>/logs/ingest.log          Append-only ingest/action audit.

Governing properties:
    * Membership is LOCATION, not a field. An item is active because it is in
      queue/, archived because it is in archive/items/. No timer, no age rule and
      no status field can clear actionable work.
    * ARCHIVE is explicit and only ever initiated by a caller (Don's UI action or
      the CLI). There is no background archival anywhere in this module.
    * Every write is atomic (tmp + rename), so a crash mid-write cannot leave a
      half item in the queue.
    * Nothing outside <root> is read or written. No 06_HANDOFFS, no ai-inbox, no
      event-ledger, no routing_state.json, no Drive.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from src.completion import contract

QUEUE_DIRNAME = "queue"
ARCHIVE_DIRNAME = "archive"
STATE_DIRNAME = "state"
LOGS_DIRNAME = "logs"

ITEMS_SUBDIR = "items"
HANDOFFS_SUBDIR = "handoffs"
LEDGER_NAME = "archive_ledger.json"
INGEST_LOG = "ingest.log"

LEDGER_SCHEMA = "gce.queue.archive_ledger"
LEDGER_VERSION = "1.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class QueueStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.queue_dir = self.root / QUEUE_DIRNAME
        self.archive_dir = self.root / ARCHIVE_DIRNAME
        self.items_dir = self.archive_dir / ITEMS_SUBDIR
        self.handoffs_dir = self.archive_dir / HANDOFFS_SUBDIR
        self.state_dir = self.root / STATE_DIRNAME
        self.logs_dir = self.root / LOGS_DIRNAME
        self.ledger_path = self.state_dir / LEDGER_NAME
        self.log_path = self.logs_dir / INGEST_LOG

    # -- filesystem ---------------------------------------------------------
    def ensure_dirs(self) -> None:
        for d in (self.queue_dir, self.items_dir, self.handoffs_dir,
                  self.state_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)

    def _atomic_write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(str(tmp), str(path))

    def log(self, event: str, **fields) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        parts = [f"{_now()} {event}"]
        for k, v in fields.items():
            parts.append(f"{k}={v}")
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(" ".join(parts) + "\n")

    # -- ledger -------------------------------------------------------------
    def read_ledger(self) -> dict:
        if not self.ledger_path.exists():
            return {"schema": LEDGER_SCHEMA, "schema_version": LEDGER_VERSION,
                    "archived": {}}
        try:
            data = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"schema": LEDGER_SCHEMA, "schema_version": LEDGER_VERSION,
                    "archived": {}}
        data.setdefault("archived", {})
        return data

    def _write_ledger(self, data: dict) -> None:
        self._atomic_write(self.ledger_path,
                           json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    # -- reading ------------------------------------------------------------
    def _read_dir(self, d: Path) -> list[dict]:
        if not d.exists():
            return []
        out = []
        for f in sorted(d.glob("*.json")):
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
        return out

    def active(self) -> list[dict]:
        """ACTIVE queue items, newest first. Never age-filtered. Never hidden."""
        items = self._read_dir(self.queue_dir)
        items.sort(key=lambda i: str(i.get("created_at", "")), reverse=True)
        return items

    def archived(self) -> list[dict]:
        items = self._read_dir(self.items_dir)
        items.sort(key=lambda i: str(i.get("created_at", "")), reverse=True)
        return items

    def find(self, item_id: str) -> tuple[dict | None, str]:
        """Locate an item by id. Returns (item, location) where location is
        'active' | 'archived' | '' when not found."""
        for it in self.active():
            if str(it.get("id")) == str(item_id):
                return it, "active"
        for it in self.archived():
            if str(it.get("id")) == str(item_id):
                return it, "archived"
        return None, ""

    # -- ingest -------------------------------------------------------------
    def ingest(self, raw: dict) -> dict:
        """Ingest ONE completion artifact. Returns a result dict.

        Exactly one active item results. Re-ingesting the same work is reported
        as a duplicate and creates nothing — this is what makes 'exactly one
        queue item' true even under repeated submission.
        """
        item = contract.validate(raw)
        self.ensure_dirs()

        name = contract.safe_name(item["id"])
        target = self.queue_dir / f"{name}.json"

        # Dedup 1: same id already active.
        if target.exists():
            self.log("ingest.duplicate", id=item["id"], reason="id already active")
            return {"ok": True, "created": False, "duplicate": True,
                    "reason": "id already active", "id": item["id"],
                    "path": str(target)}

        # Dedup 2: same content already active under a DIFFERENT id.
        for existing in self.active():
            if existing.get("content_key") == item["content_key"]:
                self.log("ingest.duplicate", id=item["id"],
                         reason=f"same work already queued as {existing.get('id')}")
                return {"ok": True, "created": False, "duplicate": True,
                        "reason": f"same work already queued as {existing.get('id')}",
                        "id": existing.get("id"), "path": str(target)}

        # Dedup 3: already archived. A completed piece of work Don has already
        # acted on must not re-enter the queue on re-submission.
        led = self.read_ledger()
        if item["content_key"] in led["archived"].get("_by_content", {}):
            prior = led["archived"]["_by_content"][item["content_key"]]
            self.log("ingest.duplicate", id=item["id"], reason=f"archived {prior}")
            return {"ok": True, "created": False, "duplicate": True,
                    "reason": f"this work was already archived ({prior})",
                    "id": item["id"]}

        item["ingested_at"] = _now()
        self._atomic_write(target, json.dumps(item, indent=2, ensure_ascii=False) + "\n")
        self.log("ingest.ok", id=item["id"], source=item["source"],
                 state=item["state"], path=str(target))
        return {"ok": True, "created": True, "duplicate": False,
                "id": item["id"], "path": str(target), "item": item}

    # -- Don actions --------------------------------------------------------
    def archive(self, item_id: str, reason: str = "don action") -> dict:
        """Explicit ARCHIVE. Removes from active queue, preserves everything.

        Only ever called from an explicit caller. There is no timer, no age
        threshold and no background path to this method.
        """
        item, loc = self.find(item_id)
        if loc != "active":
            self.log("archive.miss", id=item_id, location=loc or "absent")
            return {"ok": False, "error": f"no ACTIVE item with id '{item_id}'",
                    "id": item_id, "location": loc or "absent"}

        self.ensure_dirs()
        name = contract.safe_name(item["id"])
        dest = self.items_dir / f"{name}.json"

        # Preserve the item, adding the archive record to the stored copy.
        stored = dict(item)
        stored["archived_at"] = _now()
        stored["archive_reason"] = reason
        stored["queue_state"] = "archived"
        self._atomic_write(dest, json.dumps(stored, indent=2, ensure_ascii=False) + "\n")

        # Only now remove from active. If the preserve write failed we never get
        # here, so an item is never destroyed by a failed archive.
        src = self.queue_dir / f"{name}.json"
        src.unlink(missing_ok=True)

        led = self.read_ledger()
        led["archived"][item["id"]] = {
            "archived_at": stored["archived_at"],
            "reason": reason,
            "subject": item.get("subject"),
            "source": item.get("source"),
            "artifact": item.get("artifact"),
            "archived_item": str(dest),
        }
        led["archived"].setdefault("_by_content", {})
        led["archived"]["_by_content"][item.get("content_key", "")] = item["id"]
        self._write_ledger(led)

        self.log("archive.ok", id=item["id"], reason=reason, path=str(dest))
        return {"ok": True, "id": item["id"], "archived_item": str(dest),
                "archived_at": stored["archived_at"]}

    def handoff(self, item_id: str, recipient: str = "") -> dict:
        """Produce a usable handoff payload, then auto-archive the source.

        Order matters and is deliberate: the payload is written and verified
        BEFORE the source item is archived. A failure anywhere in payload
        creation leaves the source ACTIVE and returns visible failure evidence,
        so a queue item can never disappear without a usable copy existing.
        """
        item, loc = self.find(item_id)
        if loc != "active":
            self.log("handoff.miss", id=item_id, location=loc or "absent")
            return {"ok": False, "error": f"no ACTIVE item with id '{item_id}'",
                    "id": item_id, "location": loc or "absent"}

        self.ensure_dirs()
        name = contract.safe_name(item["id"])

        # -- 1. gather the result body -------------------------------------
        body = ""
        art = Path(item.get("artifact", ""))
        if art.exists() and art.is_file():
            try:
                body = art.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                self.log("handoff.read_fail", id=item_id, error=str(e))
                return {"ok": False, "id": item_id,
                        "error": f"could not read artifact {art}: {e}",
                        "source_state": "active (unchanged)"}

        to_line = recipient.strip() if recipient and recipient.strip() else "unassigned"
        head = [
            f"# HANDOFF — {item.get('subject', '')}",
            "",
            f"- handoff id     : {item['id']}",
            f"- source         : {item.get('source', '-')}",
            f"- state          : {item.get('state', '-')}",
            f"- created        : {item.get('created_at', '-')}",
            f"- recipient      : {to_line}",
            f"- result artifact: {item.get('artifact', '-')}",
        ]
        if item.get("project"):
            head.append(f"- project        : {item['project']}")
        if item.get("workstream"):
            head.append(f"- workstream     : {item['workstream']}")
        head += [
            "",
            "## Result",
            "",
            body.strip() if body.strip() else
            f"(no readable body at {item.get('artifact', '-')}; "
            "the artifact path above is the result of record)",
            "",
            "## Lineage",
            "",
            f"This payload was produced from VoiceBridge queue item `{item['id']}`, "
            f"which is archived automatically on successful handoff creation. "
            f"Original result: {item.get('artifact', '-')}",
            "",
        ]
        payload_text = "\n".join(head)

        # -- 2. write payload, VERIFY it -----------------------------------
        payload_path = self.handoffs_dir / f"{name}.md"
        try:
            self._atomic_write(payload_path, payload_text)
        except OSError as e:
            self.log("handoff.write_fail", id=item_id, error=str(e))
            return {"ok": False, "id": item_id,
                    "error": f"could not write handoff payload: {e}",
                    "source_state": "active (unchanged)"}

        if not payload_path.exists() or payload_path.stat().st_size == 0:
            self.log("handoff.verify_fail", id=item_id)
            return {"ok": False, "id": item_id,
                    "error": "handoff payload did not verify after write",
                    "source_state": "active (unchanged)"}

        # -- 3. sidecar so the payload is machine-findable again -------------
        sidecar = {
            "schema": "gce.queue.handoff_payload",
            "schema_version": "1.0",
            "handoff_id": item["id"],
            "created_at": _now(),
            "recipient": to_line,
            "payload_path": str(payload_path),
            "source_queue_item": item["id"],
            "subject": item.get("subject"),
            "source": item.get("source"),
            "artifact": item.get("artifact"),
            "project": item.get("project"),
            "workstream": item.get("workstream"),
            "content_key": item.get("content_key"),
        }
        sidecar_path = self.handoffs_dir / f"{name}.json"
        try:
            self._atomic_write(sidecar_path,
                               json.dumps(sidecar, indent=2, ensure_ascii=False) + "\n")
        except OSError as e:
            self.log("handoff.sidecar_fail", id=item_id, error=str(e))
            return {"ok": False, "id": item_id,
                    "error": f"payload written but sidecar failed: {e}",
                    "payload_path": str(payload_path),
                    "source_state": "active (unchanged)"}

        self.log("handoff.payload_ok", id=item_id, payload=str(payload_path))

        # -- 4. only now auto-archive the source ----------------------------
        arc = self.archive(item_id, reason=f"handoff created -> {payload_path.name}")
        if not arc.get("ok"):
            self.log("handoff.autoarchive_fail", id=item_id, error=str(arc.get("error")))
            return {"ok": False, "id": item_id,
                    "error": f"handoff payload created but auto-archive failed: "
                             f"{arc.get('error')}",
                    "payload_path": str(payload_path),
                    "source_state": "active (NOT archived — inspect)"}

        return {"ok": True, "id": item_id, "payload_path": str(payload_path),
                "sidecar_path": str(sidecar_path),
                "archived_item": arc["archived_item"],
                "recipient": to_line}

    # -- reporting ----------------------------------------------------------
    def stats(self) -> dict:
        led = self.read_ledger()
        archived_ids = [k for k in led["archived"] if not k.startswith("_")]
        return {
            "root": str(self.root),
            "active": len(self.active()),
            "archived": len(archived_ids),
            "handoff_payloads": len(list(self.handoffs_dir.glob("*.md")))
            if self.handoffs_dir.exists() else 0,
            "archived_on_disk": len(self.archived()),
            "ledger": str(self.ledger_path),
        }