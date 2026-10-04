"""Command-line face of the completion -> queue path.

This is the ONE operation a model needs to return meaningful work, and the
operator's handle on ARCHIVE / HANDOFF.

    python -m src.completion submit  <artifact.json>
    python -m src.completion list    [--archived]
    python -m src.completion show    <id>
    python -m src.completion archive <id> [--reason "..."]
    python -m src.completion handoff <id> [--to "name or free text"]
    python -m src.completion stats

Exit codes
    0  success (including a reported duplicate, which is a successful no-op)
    2  contract violation / bad usage
    3  action failed (item absent, or already archived)
"""

from __future__ import annotations

import argparse
import json
import sys

from src.completion import contract, paths
from src.completion.store import QueueStore


def _store() -> QueueStore:
    return QueueStore(paths.queue_root())


def _emit(obj) -> None:
    sys.stdout.write(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def cmd_submit(args) -> int:
    st = _store()
    try:
        item = contract.read(args.artifact)
    except contract.ContractError as e:
        sys.stderr.write(f"CONTRACT VIOLATION: {e}\n")
        return 2
    try:
        res = st.ingest(item)
    except OSError as e:
        sys.stderr.write(f"INGEST FAILED: {e}\n")
        return 3
    _emit(res)
    return 0


def cmd_list(args) -> int:
    st = _store()
    items = st.archived() if args.archived else st.active()
    rows = [
        {
            "id": i.get("id"),
            "state": i.get("state"),
            "source": i.get("source"),
            "subject": i.get("subject"),
            "created_at": i.get("created_at"),
            "artifact": i.get("artifact"),
            "project": i.get("project"),
            "workstream": i.get("workstream"),
        }
        for i in items
    ]
    _emit({"location": "archive" if args.archived else "active",
           "count": len(rows), "items": rows})
    return 0


def cmd_show(args) -> int:
    st = _store()
    item, loc = st.find(args.id)
    if not item:
        sys.stderr.write(f"NOT FOUND: {args.id}\n")
        return 3
    _emit({"location": loc, "item": item})
    return 0


def cmd_archive(args) -> int:
    st = _store()
    res = st.archive(args.id, reason=args.reason or "don action")
    _emit(res)
    return 0 if res.get("ok") else 3


def cmd_handoff(args) -> int:
    st = _store()
    res = st.handoff(args.id, recipient=args.to or "")
    _emit(res)
    return 0 if res.get("ok") else 3


def cmd_stats(args) -> int:
    _emit(_store().stats())
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m src.completion",
        description="Completion artifact -> VoiceBridge session queue.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("submit", help="ingest one completion artifact")
    s.add_argument("artifact")
    s.set_defaults(fn=cmd_submit)

    s = sub.add_parser("list", help="list active (default) or archived items")
    s.add_argument("--archived", action="store_true")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("show", help="show one item by id")
    s.add_argument("id")
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("archive", help="ARCHIVE an active item (explicit action)")
    s.add_argument("id")
    s.add_argument("--reason", default="")
    s.set_defaults(fn=cmd_archive)

    s = sub.add_parser("handoff", help="create handoff payload, then auto-archive source")
    s.add_argument("id")
    s.add_argument("--to", default="", help="recipient (free text; not required)")
    s.set_defaults(fn=cmd_handoff)

    s = sub.add_parser("stats", help="counts and paths")
    s.set_defaults(fn=cmd_stats)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())