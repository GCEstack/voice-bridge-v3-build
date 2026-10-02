"""llm.py — text rewriting via the Kimi CLI (same provider Casa Companion uses).

Shells out to `kimi -p "<prompt>"` with the stored Kimi Code credentials, so it
reuses Casa Companion's auth + default model (Kimi K3) with zero custom auth
code. Used by the proofread / concise / format voice macros to transform the
currently selected text.

The Kimi agent can be verbose, so the returned text is cleaned: leading "•"
bullets are stripped, the session-resume hint is dropped, and only the final
content is kept.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import time

logger = logging.getLogger("llm")

# Fallback locations if `kimi` is not on PATH.
_KIMI_HINTS = (
    r"C:\Users\Dekan AI Brother\.kimi-code\bin\kimi.exe",
)

_RULES = {
    "proofread": (
        "fix spelling, grammar, and punctuation; keep the meaning and length"
    ),
    "concise": (
        "rewrite to be tighter and shorter while keeping the meaning and tone"
    ),
    "format": (
        "rewrite to be professional and polished, formal tone, clean structure"
    ),
}


def _kimi_bin() -> str | None:
    found = shutil.which("kimi")
    if found:
        return found
    for hint in _KIMI_HINTS:
        import os
        if os.path.exists(hint):
            return hint
    return None


def _clean_output(raw: str) -> str:
    """Strip Kimi's agent noise and bullets from the response."""
    lines = raw.splitlines()
    kept: list[str] = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith("To resume this session:"):
            continue
        if s.startswith("kimi version"):
            continue
        # Drop a leading bullet (model's formatting) but keep the content.
        if s.startswith("• "):
            s = s[2:].strip()
        kept.append(s)
    return "\n".join(kept).strip()


def rewrite_text(mode: str, text: str, timeout: float = 120.0) -> str:
    """Rewrite ``text`` via Kimi and return the cleaned result.

    Raises RuntimeError if the Kimi CLI is missing, fails, times out, or returns
    nothing usable.
    """
    rule = _RULES.get(mode, _RULES["proofread"])
    bin = _kimi_bin()
    if not bin:
        raise RuntimeError("kimi CLI not found (kimi-code not installed?)")

    prompt = (
        "You are a strict text editor. Rewrite the text below following the "
        "rule. Output ONLY the rewritten text as the first and only content of "
        "your reply. No bullets, no labels, no explanation, no markdown, no "
        f"code fences, no preamble. Rule: {rule}. TEXT: <<<{text}>>>"
    )

    cmd = [bin, "-p", prompt, "--output-format", "text"]
    logger.info("calling kimi (%s), %d chars", mode, len(text))
    start = time.time()
    try:
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            **kwargs,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"kimi timed out after {timeout:.0f}s") from None
    except Exception as e:
        raise RuntimeError(f"failed to run kimi: {e}") from None

    elapsed = time.time() - start
    if proc.returncode != 0:
        logger.warning("kimi exit %s", proc.returncode)
        raise RuntimeError(f"kimi failed (exit {proc.returncode})")

    result = _clean_output(proc.stdout)
    logger.info("kimi done in %.1fs -> %d chars", elapsed, len(result))
    if not result:
        raise RuntimeError("kimi returned empty result")
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sample = "i wanna go to the store tomarow and buy somethings"
    print("proofread:", rewrite_text("proofread", sample))
    print("concise:", rewrite_text("concise", sample))
    print("format:", rewrite_text("format", sample))
    sys.exit(0)