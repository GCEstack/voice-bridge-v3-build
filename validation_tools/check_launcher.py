#!/usr/bin/env python3
"""Build gate: every .cmd and .bat in the tree must be CRLF, with no BOM.

The V3 launcher shipped LF-only. cmd.exe does not treat a bare LF as a line
terminator inside a parenthesised block, so `if defined PY (...) else (...)`
was shredded into the `'t' / 'exist' / 'not' / 'else'` cascade Don hit. The
failure is invisible in an editor and invisible to a syntax check — the file
looks fine and only misbehaves when cmd.exe runs it.

Same defect class as the XPI backslash bug: packaging silently corrupts.
So it is checked at build time, not at run time.

    python validation_tools/check_launcher.py            # check the tree
    python validation_tools/check_launcher.py --write    # rewrite to CRLF, then check

Exit 0 = clean, 1 = bare LF or BOM found.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET_SUFFIXES = (".cmd", ".bat")
BOM = b"\xef\xbb\xbf"
CR = 0x0D
LF = 0x0A


def find_scripts() -> list:
    return sorted(p for p in ROOT.rglob("*") if p.suffix.lower() in TARGET_SUFFIXES
                  and ".venv" not in p.parts and "__pycache__" not in p.parts)


def scan(path: Path) -> dict:
    """Report bare-LF count, CRLF count, and BOM presence for one file."""
    raw = path.read_bytes()
    has_bom = raw.startswith(BOM)
    body = raw[len(BOM):] if has_bom else raw
    crlf = 0
    bare_lf = 0
    for i, b in enumerate(body):
        if b == LF:
            if i > 0 and body[i - 1] == CR:
                crlf += 1
            else:
                bare_lf += 1
    trailing_newline = body.endswith(b"\n")
    return {
        "path": path,
        "bytes": len(raw),
        "crlf": crlf,
        "bare_lf": bare_lf,
        "has_bom": has_bom,
        "trailing_newline": trailing_newline,
    }


def to_crlf(path: Path) -> None:
    """Rewrite with CRLF, no BOM, exactly one trailing newline."""
    raw = path.read_bytes()
    if raw.startswith(BOM):
        raw = raw[len(BOM):]
    text = raw.decode("utf-8", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.rstrip("\n") + "\n"
    path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true",
                    help="rewrite every .cmd/.bat to CRLF before checking")
    args = ap.parse_args()

    scripts = find_scripts()
    if not scripts:
        print("[PASS] no .cmd or .bat files found — nothing to check")
        return 0

    if args.write:
        for p in scripts:
            to_crlf(p)
            print(f"[WRITE] {str(p.relative_to(ROOT))} -> CRLF, no BOM")

    failures = []
    print()
    for p in scripts:
        r = scan(p)
        rel = r["path"].relative_to(ROOT)
        if r["bare_lf"] or r["has_bom"] or not r["trailing_newline"]:
            failures.append(rel)
            print(f"[FAIL] {rel}")
            if r["bare_lf"]:
                print(f"       {r['bare_lf']} bare LF — cmd.exe will mis-parse this file")
            if r["has_bom"]:
                print("       UTF-8 BOM present — cmd.exe will echo garbage before the first command")
            if not r["trailing_newline"]:
                print("       no trailing newline")
        else:
            print(f"[PASS] {str(rel):<28} {r['crlf']} CRLF, no bare LF, no BOM")

    print()
    if failures:
        print(f"[FAIL] {len(failures)} launcher file(s) would break under cmd.exe:")
        for f in failures:
            print(f"       {f}")
        print("       fix: python validation_tools/check_launcher.py --write")
        return 1

    print(f"[PASS] {len(scripts)} launcher file(s) are CRLF-clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())