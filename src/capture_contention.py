"""Microphone contention — V3 yields to the live V1 bridge.

V3 never steals the microphone. If V1 is holding the mic, V3 waits. This is
why V3 could run as a shadow lane beside the live tree without a cutover.

V3.1: contention applies to the MIC source only. A queued file does not touch
the mic, so it is never blocked by V1.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

logger = logging.getLogger("v3.contention")

# V1's single-instance mutex, if V1 is running.
_V1_MUTEX_NAME = "Global\\VoiceBridge_V1_SingleInstance"


def is_v1_running() -> bool:
    """True if the frozen V1 bridge appears to be running. Never raises."""
    try:
        import ctypes

        handle = ctypes.windll.kernel32.OpenMutexW(0x1000, False, _V1_MUTEX_NAME)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
    except Exception:
        # Absence of proof is not proof of absence: report not-running rather
        # than failing the check, and let the caller proceed.
        return False
    return False


class ContentionAwareCapture:
    """Wraps a capture start and defers it while V1 holds the microphone."""

    def __init__(self, poll_seconds: float = 5.0, log_wait: bool = True):
        self.poll_seconds = float(poll_seconds)
        self.log_wait = log_wait

    def wait_for_mic(self, timeout: float = 0.0) -> bool:
        """Block until V1 releases the mic. Returns True if the mic is free."""
        started = time.monotonic()
        warned = False
        while is_v1_running():
            if not warned and self.log_wait:
                logger.info("V1 holds the microphone — V3 capture deferred")
                warned = True
            if timeout and (time.monotonic() - started) > timeout:
                logger.warning(f"mic still held by V1 after {timeout:.0f}s — giving up")
                return False
            time.sleep(self.poll_seconds)
        return True