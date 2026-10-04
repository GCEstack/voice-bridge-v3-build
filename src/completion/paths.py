"""Queue configuration — resolved INSIDE the live product tree. No fallbacks out.

One live source of truth for queue paths. Paths are derived from the product
root, not hardcoded and not read from the legacy handoff_queue block, so a
stale absolute path in config.json cannot silently re-point the queue at a
frozen tree.
"""

from __future__ import annotations

from pathlib import Path

from src.completion.store import QueueStore

# The product root is the directory containing src/.
PRODUCT_ROOT = Path(__file__).resolve().parents[2]

# Overridable for tests and for a deliberate relocation, but the default can
# never escape the product tree.
ENV_QUEUE_ROOT = "GCE_QUEUE_ROOT"


def queue_root() -> Path:
    import os
    override = os.environ.get(ENV_QUEUE_ROOT)
    if override and override.strip():
        return Path(override).expanduser().resolve()
    return PRODUCT_ROOT


def store() -> QueueStore:
    return QueueStore(queue_root())