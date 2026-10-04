"""One-time: repoint v3-build config.json off the frozen voice-bridge tree.

Replaces the legacy `handoff_queue` / `queue_refresh` / `queue_filters` blocks
with a single `queue` block whose paths are relative to the product root.
Absolute paths into a frozen tree are what created the split brain; they are
removed rather than corrected.
"""
import json
import os
from collections import OrderedDict
from pathlib import Path

cfg_path = Path(__file__).resolve().parents[1] / "config.json"
cfg = json.loads(cfg_path.read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)

# Record what is being removed, for the return package.
removed = [k for k in ("handoff_queue", "queue_refresh", "queue_filters") if k in cfg]

for k in removed:
    cfg.pop(k, None)

cfg["queue"] = OrderedDict([
    ("_what", "Don-facing session queue. Completed work awaiting Don's decision. "
              "One ingest, one active item, two explicit actions: ARCHIVE and HANDOFF."),
    ("_paths", "Resolved relative to this product tree by src/completion/paths.py. "
               "There is deliberately no absolute path here: the previous absolute "
               "paths pointed into the frozen voice-bridge tree, which made that tree "
               "a live runtime dependency and split the product across two folders."),
    ("root", "."),
    ("refresh_seconds", 30),
    ("_no_age_rule", "No age-based archival exists. An item leaves the active queue "
                     "only through Don's ARCHIVE action or a successful HANDOFF."),
    ("_ingest", "python -m src.completion submit <artifact.json>  — the single "
                "operation a model uses to return meaningful work."),
    ("_actions", "python -m src.completion archive <id> | handoff <id>  — also "
                 "available as the ARCHIVE / HANDOFF buttons in the queue panel."),
])

# The deprecated ai-inbox lanes statement is still true and still required; keep it.
out = json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"
tmp = cfg_path.with_suffix(".json.tmp")
tmp.write_text(out, encoding="utf-8")
os.replace(str(tmp), str(cfg_path))

print("removed blocks :", ", ".join(removed) or "(none)")
print("config written :", cfg_path)
print("abs refs to frozen tree remaining:",
      cfg_path.read_text(encoding="utf-8").count("voice-bridge\\\\queue"))