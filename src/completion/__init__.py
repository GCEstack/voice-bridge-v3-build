"""Completion / queue package.

The single operating path for the VoiceBridge session queue:

    model completes meaningful work
      -> one completion artifact
      -> ONE ingest (ingest.py / cli.py)
      -> one live queue item
      -> Don: ARCHIVE or HANDOFF
      -> source item archived

Nothing in this package reads 06_HANDOFFS, ai-inbox, the event ledger,
routing_state.json, the legacy producer, or any Drive path.
"""

from src.completion import contract, paths, store  # noqa: F401

__all__ = ["contract", "paths", "store"]