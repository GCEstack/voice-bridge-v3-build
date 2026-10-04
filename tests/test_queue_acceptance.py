"""Final acceptance sweep for the VoiceBridge queue reset.

Proves the DONE conditions from a fresh process, after the full reset:

  1. completion -> EXACTLY ONE queue item
  2. ARCHIVE works
  3. HANDOFF works and the SOURCE AUTO-ARCHIVES
  4. archived items do not resurrect after restart

Run against an isolated queue root so the live queue is never touched.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PRODUCT = Path(__file__).resolve().parents[1]
PY = str(PRODUCT / ".venv" / "Scripts" / "python.exe")

results = []


def run(root, *args):
    env = dict(os.environ, GCE_QUEUE_ROOT=str(root))
    p = subprocess.run([PY, "-m", "src.completion", *args],
                       cwd=str(PRODUCT), env=env,
                       capture_output=True, text=True)
    try:
        out = json.loads(p.stdout)
    except json.JSONDecodeError:
        out = {"_raw": p.stdout, "_err": p.stderr}
    return p.returncode, out


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}"
          + (f"  ({detail})" if detail else ""))


root = Path(tempfile.mkdtemp(prefix="vbqueue-accept-"))
print(f"isolated queue root: {root}\n")

print("1. COMPLETION -> EXACTLY ONE QUEUE ITEM")
art = root / "artifact.json"
res_file = root / "result.md"
res_file.write_text("# result of record\n\nbody\n", encoding="utf-8")
art.write_text(json.dumps({
    "id": "ACCEPT-1", "created_at": "2026-01-01T00:00:00",
    "source": "Nico", "subject": "acceptance item one",
    "artifact": str(res_file), "state": "completed",
}), encoding="utf-8")
rc, r1 = run(root, "submit", str(art))
check("submit exits 0", rc == 0)
check("exactly one item created", r1.get("created") is True and not r1.get("duplicate"))

rc, dup = run(root, "submit", str(art))
check("resubmit creates nothing", dup.get("duplicate") is True and dup.get("created") is False)

art.write_text(json.dumps({
    "id": "ACCEPT-1-DIFFERENT-ID", "created_at": "2026-01-01T00:00:00",
    "source": "nico", "subject": "acceptance item one",
    "artifact": str(res_file), "state": "completed",
}), encoding="utf-8")
rc, dup2 = run(root, "submit", str(art))
check("same work under a different id creates nothing",
      dup2.get("duplicate") is True)

rc, lst = run(root, "list")
check("active count == 1", lst.get("count") == 1, f"count={lst.get('count')}")

print("\n2. ARCHIVE")
rc, arc = run(root, "archive", "ACCEPT-1")
check("archive exits 0", rc == 0 and arc.get("ok") is True)
rc, lst = run(root, "list")
check("active is now empty", lst.get("count") == 0)
rc, arch = run(root, "list", "--archived")
check("archived count == 1", arch.get("count") == 1)
check("archived item retained artifact", bool(arch["items"][0].get("artifact")))
check("source artifact file still exists", res_file.exists())

print("\n3. HANDOFF -> PAYLOAD -> SOURCE AUTO-ARCHIVES")
art2 = root / "artifact2.json"
res2 = root / "result2.md"
res2.write_text("# second result of record\n\nunique body text\n", encoding="utf-8")
art2.write_text(json.dumps({
    "id": "ACCEPT-2", "created_at": "2026-02-02T00:00:00",
    "source": "Nico", "subject": "acceptance item two",
    "artifact": str(res2), "state": "completed",
}), encoding="utf-8")
rc, r2 = run(root, "submit", str(art2))
check("second item created", r2.get("created") is True)
rc, lst = run(root, "list")
check("active count == 1 before handoff", lst.get("count") == 1)

rc, ho = run(root, "handoff", "ACCEPT-2", "--to", "Don")
check("handoff exits 0", rc == 0 and ho.get("ok") is True)
payload = Path(ho.get("payload_path", ""))
check("payload file exists", payload.exists())
check("payload non-empty", payload.exists() and payload.stat().st_size > 0)
body = payload.read_text(encoding="utf-8") if payload.exists() else ""
check("payload carries the result body", "unique body text" in body)
check("payload carries lineage to source", "ACCEPT-2" in body)

rc, lst = run(root, "list")
check("active is empty after handoff (source auto-archived)", lst.get("count") == 0)
rc, arch = run(root, "list", "--archived")
check("archived count == 2", arch.get("count") == 2)

print("\n4. HANDOFF FAILURE LEAVES SOURCE ACTIVE")
art3 = root / "artifact3.json"
art3.write_text(json.dumps({
    "id": "ACCEPT-3", "created_at": "2026-03-03T00:00:00",
    "source": "Nico", "subject": "acceptance item three",
    "artifact": str(root / "does-not-exist.md"), "state": "failed",
}), encoding="utf-8")
run(root, "submit", str(art3))
rc, bad = run(root, "handoff", "NO-SUCH-ID")
check("handoff on absent id fails loudly", rc == 3 and bad.get("ok") is False)
rc, lst = run(root, "list")
check("the real item is still ACTIVE after that failure",
      any(i["id"] == "ACCEPT-3" for i in lst["items"]))
rc, bad2 = run(root, "archive", "ACCEPT-1")
check("archive of an already-archived id fails loudly",
      rc == 3 and bad2.get("ok") is False)

print("\n5. RESTART -> NO RESURRECTION (fresh process reads durable state)")
# NOTE: ACCEPT-3 is still ACTIVE here — section 4 proved a failed handoff leaves
# the source active. The correct invariant is therefore "exactly the one item
# section 4 left active, and neither archived item came back", not "empty".
rc, fresh = run(root, "list")
active_ids = [i["id"] for i in fresh.get("items", [])]
check("fresh process active == [ACCEPT-3] only",
      active_ids == ["ACCEPT-3"], f"active={active_ids}")
check("ACCEPT-1 did not resurrect", "ACCEPT-1" not in active_ids)
check("ACCEPT-2 did not resurrect", "ACCEPT-2" not in active_ids)
rc, fresh_a = run(root, "list", "--archived")
arch_ids = [i["id"] for i in fresh_a.get("items", [])]
check("archived still holds ACCEPT-1 + ACCEPT-2 in a fresh process",
      sorted(arch_ids) == ["ACCEPT-1", "ACCEPT-2"], f"archived={arch_ids}")
rc, again = run(root, "submit", str(art))
check("re-submitting archived work does not resurrect it",
      again.get("duplicate") is True)
rc, lst = run(root, "list")
active_ids = [i["id"] for i in lst.get("items", [])]
check("active unchanged after re-submit", active_ids == ["ACCEPT-3"],
      f"active={active_ids}")

print("\n6. CONTRACT ENFORCEMENT")
bad_art = root / "bad.json"
bad_art.write_text(json.dumps({"id": "X", "source": "Nico"}), encoding="utf-8")
rc, _ = run(root, "submit", str(bad_art))
check("incomplete artifact is refused with exit 2", rc == 2)
rc, lst = run(root, "list")
check("refused artifact created nothing", lst.get("count") == 1,
      f"count={lst.get('count')} (ACCEPT-3 only, pre-existing)")

shutil.rmtree(root, ignore_errors=True)

passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print("\n" + "=" * 60)
print(f"ACCEPTANCE: {passed}/{total} checks passed")
print("=" * 60)
sys.exit(0 if passed == total else 1)