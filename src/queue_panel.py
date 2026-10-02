"""Handoff review surface — the Don/Coda queue panel inside VoiceBridge.

VoiceBridge is a REVIEW surface only. It is NOT a transport layer.
This module reads one resolved queue registry and renders it. It never
creates, routes, claims or mutates a handoff record.

RECORD CONTRACT — one JSON file per handoff, written by the PRODUCER side
(Framework / Cable Car / the artifact writer), NEVER by VoiceBridge:

    id            str              stable correlation id
    project       str              e.g. "EC8"
    workstream    str              e.g. "Parent Quant"
    from          str              producing SEAT (MODEL != SEAT)
    to            str              receiving SEAT
    status        str              ready | reviewed | blocked   (producer field)
    source_type   str              code | doc | config | decision | evidence
    local_path    str              local artifact path          ([Copy Path])
    drive_file_id str | null       Cable Car correlation, if transported
    created_at    str              ISO timestamp
    subject       str              one-line summary
    body          str              longer text shown in the detail pane

COLUMN ORDER (2026-09-28 Don/Serafina spec):
    1. PROJECT   - Folder name (clickable) → opens runtime_root in Explorer
    2. SUBJECT   - Handoff title (expands view)
    3. STATUS    - ready/claimed/reviewed (visual badge)
    4. FROM      - Sending seat (color coded)
    5. TIME      - Human relative (tooltip: absolute)
    6. WORKSTREAM- Sub-path (clickable)

FROM SEAT COLORS:
    Nico      - Orange   #f97316
    Luce      - Purple   #a855f7
    Coda      - Blue     #3b82f6
    Chiave    - Teal     #14b8a6
    Falcon    - Green    #22c55e
    Corrado   - Red      #ef4444
    Vittorio  - Yellow   #eab308
    Talon     - Brown    #92400e
    Keel      - Gray     #6b7280
    Don       - Gold     #d97706
    Enzo      - Cyan     #06b6d4
    Serafina  - Magenta  #d946ef

ACTIONS:
    [Open]        os.startfile(local_path)
    [Copy Text]   metadata header + body -> clipboard
    [Copy Path]   local_path -> clipboard
    [Dismiss]     local reviewer state ONLY (queue_local.json).
                  Dismiss NEVER touches `status` in the registry.

DESIGN RULES (Don strategy E, 2026-09-26):
  - READ ONLY against the registry. No writer, no router, no intake crawl.
  - Missing registry shows as offline and is never auto-created.
  - The panel owns no routing semantics and no department destinations.
  - Paths are data: handoff_queue in config.json.
  - The registry path must be a LOCAL folder. Never a Drive mount — Drive
    is reached through Cable Car, not through a synchronous Tk scan.
  - The panel writes exactly one file of its own (local_state) and nothing
    else. A broken panel must never take the dictation window down: the
    mount in _build_ui() is wrapped in try/except.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import ttk

DEFAULT_LIMIT = 300

# FROM seat colors per Don/Serafina spec (2026-09-28)
SEAT_COLORS = {
    "Nico": "#f97316",      # Orange
    "Luce": "#a855f7",      # Purple
    "Coda": "#3b82f6",      # Blue
    "Chiave": "#14b8a6",    # Teal
    "Falcon": "#22c55e",    # Green
    "Corrado": "#ef4444",   # Red
    "Vittorio": "#eab308",  # Yellow
    "Talon": "#92400e",     # Brown
    "Keel": "#6b7280",      # Gray
    "Don": "#d97706",       # Gold
    "Enzo": "#06b6d4",      # Cyan
    "Serafina": "#d946ef",  # Magenta
}

# PROJECT → runtime_root mapping (hardcoded for VoiceBridge - no Node.js dependency)
PROJECT_RUNTIME_MAP = {
    "EC8": "C:\\Users\\Dekan AI Brother\\GCE_DON\\GCE_EC8",
    "FRAMEWORK": "C:\\Users\\Dekan AI Brother\\GCE_ORG",
    "DEVPAD": "C:\\Users\\Dekan AI Brother\\GCE_DON\\command-center",
    "CABLE_CAR": "C:\\Users\\Dekan AI Brother\\GCE_DON\\command-center\\cable-car",
    "GCE_STACK": "C:\\Users\\Dekan AI Brother\\GCE_ORG",
}


# ---------------------------------------------------------------------
# pure helpers (headless-testable)
# ---------------------------------------------------------------------
def _mtime_iso(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    except Exception:
        return ""


def _read_body(path: Path, limit: int = 800) -> str:
    try:
        if path.suffix.lower() == ".json":
            m = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(m, dict):
                return str(m.get("body", ""))[:limit]
        elif path.suffix.lower() in (".md", ".txt"):
            return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        pass
    return ""


def normalize_record(m: dict, path: Path) -> dict:
    """Map one registry JSON onto the panel record. Missing fields degrade."""
    if not isinstance(m, dict):
        raise ValueError("record is not an object")
    local = str(m.get("local_path") or m.get("artifact") or "")
    subject = str(m.get("subject") or "")
    if not subject:
        subject = Path(local).stem if local else path.stem
    body = str(m.get("body") or "")
    if not body:
        body = _read_body(Path(local)) if local else _read_body(path)
    return {
        "id": str(m.get("id") or path.stem),
        "project": str(m.get("project") or "-"),
        "workstream": str(m.get("workstream") or "-"),
        "from": str(m.get("from") or "?"),
        "to": str(m.get("to") or "-"),
        "status": str(m.get("status") or "ready"),
        "source_type": str(m.get("source_type") or "-"),
        "local_path": local,
        "drive_file_id": str(m.get("drive_file_id") or ""),
        "created_at": str(m.get("created_at") or _mtime_iso(path)),
        "subject": subject[:70],
        "body": body,
        "file": str(path),
        "source": str(m.get("source") or "Queue"),
    }


def scan_registry(path: str, limit: int = DEFAULT_LIMIT, sources: list[dict] = None) -> tuple[list[dict], bool]:
    """Read the handoff registry. Returns (records newest-first, offline).

    Missing / unreadable folder -> ([], True). Never auto-creates it.
    A single malformed file is skipped; it never aborts the scan.
    Supports multiple source roots via sources config.
    """
    items: list[dict] = []

    if sources:
        for src in sources:
            src_path = Path(src.get("path", ""))
            src_label = src.get("label", src_path.name)
            if src_path.exists() and src_path.is_dir():
                for f in sorted(src_path.glob("*.json")):
                    try:
                        m = json.loads(f.read_text(encoding="utf-8"))
                        rec = normalize_record(m, f)
                        rec["source"] = src_label
                        items.append(rec)
                    except Exception:
                        continue
    else:
        p = Path(path) if path else None
        if p is None or not path.strip() or not p.exists() or not p.is_dir():
            return [], True
        for f in sorted(p.glob("*.json")):
            try:
                m = json.loads(f.read_text(encoding="utf-8"))
                items.append(normalize_record(m, f))
            except Exception:
                continue

    items.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
    return items[: max(1, int(limit))], False


def visible(items: list[dict], dismissed: set[str], show_dismissed: bool = False) -> list[dict]:
    if show_dismissed:
        return list(items)
    return [i for i in items if i.get("id") not in dismissed]


def tag_for(status: str, is_dismissed: bool) -> str:
    if is_dismissed:
        return "dismissed"
    s = (status or "").lower()
    if s in ("reviewed", "claimed", "done"):
        return "reviewed"
    if s in ("blocked", "error"):
        return "blocked"
    return "ready"


def record_text(rec: dict) -> str:
    """Clipboard payload for [Copy Text]: metadata header + body."""
    return "\n".join([
        f"id: {rec.get('id', '-')}",
        f"project: {rec.get('project', '-')}    workstream: {rec.get('workstream', '-')}",
        f"from: {rec.get('from', '?')}    to: {rec.get('to', '-')}",
        f"status: {rec.get('status', '-')}    source_type: {rec.get('source_type', '-')}",
        f"local_path: {rec.get('local_path', '')}",
        f"drive_file_id: {rec.get('drive_file_id') or '-'}",
        f"created_at: {rec.get('created_at', '-')}",
        f"subject: {rec.get('subject', '-')}",
        "",
        rec.get("body") or "(no body)",
    ])


def load_dismissed(path: str) -> set[str]:
    """Read the panel's OWN reviewer state. Absent/corrupt -> empty set."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return set()
    if isinstance(data, list):
        return {str(x) for x in data}
    if isinstance(data, dict):
        return {str(x) for x in data.get("dismissed", [])}
    return set()


def save_dismissed(path: str, ids: set[str]) -> bool:
    """Write the panel's OWN reviewer state. Never touches the registry."""
    if not path:
        return False
    try:
        payload = {
            "schema": "voicebridge.queue.local_state",
            "dismissed": sorted(str(i) for i in ids),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        Path(path).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception:
        return False


def open_artifact(path: str) -> tuple[bool, str]:
    """Shell-open a local artifact. Never opens a URL, never resolves Drive."""
    if not path or not str(path).strip():
        return False, "no local artifact"
    p = Path(path)
    if not p.exists():
        return False, f"not found: {path}"
    try:
        os.startfile(str(p))
        return True, str(p)
    except Exception as e:
        return False, str(e)


def open_project_folder(project: str) -> tuple[bool, str]:
    """Open Windows Explorer at the project's runtime_root."""
    runtime = PROJECT_RUNTIME_MAP.get(project.upper())
    if not runtime:
        return False, f"unknown project: {project}"
    p = Path(runtime)
    if not p.exists():
        return False, f"folder not found: {runtime}"
    try:
        os.startfile(str(p))
        return True, str(p)
    except Exception as e:
        return False, str(e)


def format_human_time(iso_timestamp: str) -> str:
    """Convert ISO timestamp to human relative format."""
    if not iso_timestamp:
        return "-"
    try:
        dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
        now = datetime.now(dt.tzinfo)
        diff = now - dt

        if diff < timedelta(minutes=1):
            return "just now"
        elif diff < timedelta(hours=1):
            mins = int(diff.total_seconds() / 60)
            return f"{mins}m ago"
        elif diff < timedelta(days=1):
            hours = int(diff.total_seconds() / 3600)
            return f"{hours}h ago"
        elif diff < timedelta(days=2):
            return "Yesterday"
        elif diff < timedelta(days=7):
            days = diff.days
            return f"{days}d ago"
        else:
            return dt.strftime("%b %d")
    except Exception:
        return "-"


def get_seat_color(seat: str) -> str:
    """Get the color for a seat, or default gray for unknown seats."""
    return SEAT_COLORS.get(seat, "#6b7280")


class ToolTip:
    """Simple tooltip for Tk widgets."""

    def __init__(self, widget, text_func):
        self.widget = widget
        self.text_func = text_func
        self.tip_window = None
        self.widget.bind("<Enter>", self._show)
        self.widget.bind("<Leave>", self._hide)

    def _show(self, _event=None):
        if self.tip_window or not self.widget.winfo_exists():
            return
        text = self.text_func()
        if not text:
            return
        self.tip_window = tk.Toplevel(self.widget)
        self.tip_window.wm_overrideredirect(True)
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height()
        self.tip_window.wm_geometry(f"+{x}+{y}")
        label = tk.Label(self.tip_window, text=text, background="#fef9c3",
                         relief="solid", borderwidth=1, font=("Arial", 8))
        label.pack()
        self.tip_window.update_idletasks()

    def _hide(self, _event=None):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


# ---------------------------------------------------------------------
# panel
# ---------------------------------------------------------------------
class QueuePanel(tk.Frame):
    """Read-only handoff queue embedded in the bridge window."""

    COLS = ("project", "subject", "status", "from", "time", "workstream", "source")
    WIDTHS = (("project", 80), ("subject", 120), ("status", 74),
              ("from", 68), ("time", 60), ("workstream", 80), ("source", 70))

    def __init__(self, master, config: dict):
        super().__init__(master)
        hq = dict(config.get("handoff_queue") or {})
        self.registry_path = str(hq.get("registry_path", "") or "")
        self.sources = list(hq.get("sources") or [])
        # floor at 1s: a bad config value must never busy-loop the Tk thread
        self.refresh_seconds = max(1.0, float(hq.get("refresh_seconds", 30) or 30))
        self.limit = int(hq.get("limit", DEFAULT_LIMIT) or DEFAULT_LIMIT)
        self.state_path = str(hq.get("local_state", "") or "")
        self.dismissed: set[str] = load_dismissed(self.state_path)
        self.show_dismissed = False
        self._all: list[dict] = []
        self._items: list[dict] = []
        self._build()
        self.refresh()
        self.after(int(self.refresh_seconds * 1000), self._auto_refresh)

    # -- UI --------------------------------------------------------------
    def _build(self):
        head = tk.Frame(self)
        head.pack(fill="x")
        tk.Label(head, text="HANDOFF QUEUE", font=("Arial", 11, "bold")).pack(side="left")
        self.offline_label = tk.Label(head, text="", fg="#b45309", font=("Arial", 8))
        self.offline_label.pack(side="left", padx=8)
        ttk.Button(head, text="Refresh", command=self.refresh, width=9).pack(side="right")

        self.dismissed_var = tk.BooleanVar(value=False)
        self.dismissed_btn = ttk.Checkbutton(
            head, text="Show dismissed (0)", variable=self.dismissed_var,
            command=self._toggle_dismissed)
        self.dismissed_btn.pack(side="right", padx=6)

        self.tree = ttk.Treeview(self, columns=self.COLS, show="headings", height=11)
        for col, width in self.WIDTHS:
            self.tree.heading(col, text=col.upper())
            self.tree.column(col, width=width, anchor="w")
        self.tree.tag_configure("ready", background="#fef3c7")
        self.tree.tag_configure("reviewed", background="#dbeafe")
        self.tree.tag_configure("blocked", background="#fee2e2")
        self.tree.tag_configure("dismissed", background="#e5e7eb")
        self.tree.pack(fill="both", expand=True, pady=(4, 4))
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-Button-1>", self._on_double_click)

        def time_tooltip():
            sel = self._selected()
            if sel:
                return str(sel.get("created_at", "-"))
            return ""
        ToolTip(self.tree, time_tooltip)

        self.detail = tk.Text(self, height=5, wrap="word", state="disabled",
                              font=("Consolas", 9), background="#f8fafc")
        self.detail.pack(fill="x", pady=(0, 4))

        actions = tk.Frame(self)
        actions.pack(fill="x", pady=(0, 2))
        self.btn_open = ttk.Button(actions, text="Open", width=11, command=self._on_open)
        self.btn_open.pack(side="left", padx=2)
        self.btn_copy_text = ttk.Button(actions, text="Copy Text", width=11,
                                        command=self._on_copy_text)
        self.btn_copy_text.pack(side="left", padx=2)
        self.btn_copy_path = ttk.Button(actions, text="Copy Path", width=11,
                                        command=self._on_copy_path)
        self.btn_copy_path.pack(side="left", padx=2)
        self.btn_dismiss = ttk.Button(actions, text="Dismiss", width=11,
                                      command=self._on_dismiss)
        self.btn_dismiss.pack(side="left", padx=2)
        self.btn_open_folder = ttk.Button(actions, text="Open folder", width=11,
                                          command=self._open_handoff_folder)
        self.btn_open_folder.pack(side="left", padx=2)
        self.btn_archive = ttk.Button(actions, text="Archive reviewed", width=15,
                                       command=self._on_archive)
        self.btn_archive.pack(side="left", padx=2)

        self.action_status = tk.Label(self, text="", fg="#15803d", font=("Arial", 9))
        self.action_status.pack(anchor="w")
        self._set_action("read-only review surface — no records are written by VoiceBridge", True)

    # -- behavior --------------------------------------------------------
    def refresh(self):
        self._all, offline = scan_registry(self.registry_path, self.limit, self.sources)
        self._show_empty_diagnostic(offline)
        self._render()

    def _show_empty_diagnostic(self, offline: bool):
        visible_count = len(visible(self._all, self.dismissed, self.show_dismissed))
        dismissed_count = len(self.dismissed)
        path_info = f"Registry: {self.registry_path}"

        if visible_count == 0 and not offline:
            if dismissed_count > 0:
                self._set_action(
                    f"Queue empty. {dismissed_count} dismissed items hidden. "
                    f"Check 'Show dismissed' to view. {path_info}", False)
            else:
                self._set_action(f"Queue empty. {path_info}", False)
        elif offline:
            self._set_action(f"Registry offline. {path_info}", False)
        else:
            self._set_action(f"{len(self._all)} record(s) — {path_info}", True)

    def _open_handoff_folder(self):
        """Open the registry folder in Windows Explorer."""
        if not self.registry_path:
            self._set_action("no handoff folder configured", False)
            return
        p = Path(self.registry_path)
        if not p.exists():
            self._set_action(f"folder not found: {self.registry_path}", False)
            return
        try:
            os.startfile(str(p))
            self._set_action(f"opened {self.registry_path}", True)
        except Exception as e:
            self._set_action(f"failed: {e}", False)

    def _render(self):
        selected_id = self._selected_id()
        self._items = visible(self._all, self.dismissed, self.show_dismissed)
        self.tree.delete(*self.tree.get_children())
        used: set[str] = set()
        for n, it in enumerate(self._items):
            rid = str(it.get("id") or "") or f"row-{n}"
            while rid in used:
                rid = f"{rid}-{n}"
            used.add(rid)
            iso_time = str(it.get("created_at", ""))
            when = format_human_time(iso_time)
            dismissed = it.get("id") in self.dismissed
            self.tree.insert("", "end", iid=rid, values=(
                it.get("project", "-"),
                it.get("subject", "-"),
                it.get("status", "-"),
                it.get("from", "?"),
                when,
                it.get("workstream", "-"),
                it.get("source", "-")),
                tags=(tag_for(str(it.get("status", "")), dismissed),))
        self.dismissed_btn.config(text=f"Show dismissed ({len(self.dismissed)})")
        if selected_id and self.tree.exists(selected_id):
            self.tree.selection_set(selected_id)
            self._show_detail(self._by_id(selected_id))
        else:
            self._set_detail("")

    def _auto_refresh(self):
        try:
            self.refresh()
        finally:
            self.after(int(self.refresh_seconds * 1000), self._auto_refresh)

    def _toggle_dismissed(self):
        self.show_dismissed = bool(self.dismissed_var.get())
        self._render()

    def _by_id(self, rid: str) -> dict | None:
        for it in self._all:
            if it.get("id") == rid:
                return it
        return None

    def _selected_id(self) -> str:
        sel = self.tree.selection()
        return str(sel[0]) if sel else ""

    def _selected(self) -> dict | None:
        rid = self._selected_id()
        if rid:
            return self._by_id(rid)
        return None

    def _on_select(self, _event):
        self._show_detail(self._selected())

    def _on_double_click(self, _event):
        region = self.tree.identify_region(_event.x, _event.y)
        if region != "cell":
            return
        column = self.tree.identify_column(_event.x)
        item = self._selected()
        if not item:
            return
        col_index = int(column.replace("#", "")) - 1
        col_name = self.COLS[col_index] if col_index < len(self.COLS) else None
        if col_name == "project":
            proj = item.get("project", "")
            if proj:
                ok, info = open_project_folder(proj)
                self._set_action(f"opened {proj} -> {info}" if ok else f"failed: {info}", ok)
        elif col_name == "from":
            seat = item.get("from", "")
            if seat:
                color = get_seat_color(seat)
                self._set_action(f"from: {seat} (color: {color})", True)

    def _show_detail(self, it: dict | None):
        if not it:
            self._set_detail("")
            return
        self._set_detail(
            f"from: {it.get('from','?')}  ->  {it.get('to','-')}   |   "
            f"status: {it.get('status','-')}   |   type: {it.get('source_type','-')}\n"
            f"project: {it.get('project','-')}  /  workstream: {it.get('workstream','-')}\n"
            f"path: {it.get('local_path','') or '(no local artifact)'}"
            f"{'   drive: ' + it['drive_file_id'] if it.get('drive_file_id') else ''}\n"
            f"record: {it.get('file','')}\n\n"
            f"{it.get('body','') or '(no body)'}")

    def _set_detail(self, text: str):
        self.detail.config(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.config(state="disabled")

    def _set_action(self, text: str, ok: bool):
        self.action_status.config(text=text, fg="#15803d" if ok else "#b91c1c")

    # -- actions ---------------------------------------------------------
    def _on_open(self):
        it = self._selected()
        if not it:
            self._set_action("select a record first", False)
            return
        ok, info = open_artifact(it.get("local_path", ""))
        self._set_action(("OPENED -> " if ok else "OPEN FAILED: ") + info, ok)

    def _on_copy_text(self):
        it = self._selected()
        if not it:
            self._set_action("select a record first", False)
            return
        self._clipboard(record_text(it))
        self._set_action(f"copied text for {it.get('id','')}", True)

    def _on_copy_path(self):
        it = self._selected()
        if not it:
            self._set_action("select a record first", False)
            return
        path = str(it.get("local_path", ""))
        if not path:
            self._set_action("record has no local_path", False)
            return
        self._clipboard(path)
        self._set_action("copied path", True)

    def _on_dismiss(self):
        it = self._selected()
        if not it:
            self._set_action("select a record first", False)
            return
        rid = str(it.get("id", ""))
        if rid in self.dismissed:
            self.dismissed.discard(rid)
            verb = "restored"
        else:
            self.dismissed.add(rid)
            verb = "dismissed"
        if not save_dismissed(self.state_path, self.dismissed):
            if verb == "dismissed":
                self.dismissed.discard(rid)
            else:
                self.dismissed.add(rid)
            self._set_action("could not write local state — dismissal not kept", False)
            self._render()
            return
        self._set_action(
            f"{verb} {rid} (local reviewer state only — registry untouched)", True)
        self._render()

    def _on_archive(self):
        reviewed = [it for it in self._all
                    if str(it.get("status", "")).lower() in ("reviewed", "claimed", "done")]
        if not reviewed:
            self._set_action("no reviewed items to archive", False)
            return
        n = len(reviewed)
        confirm = tk.messagebox.askyesno(
            "Archive reviewed",
            f"Archive {n} reviewed handoff(s)?\n\nThis will move them to the _archive subfolder.")
        if not confirm:
            return
        archive_dir = Path(self.registry_path) / "_archive"
        try:
            archive_dir.mkdir(exist_ok=True)
        except Exception as e:
            self._set_action(f"could not create archive folder: {e}", False)
            return
        archived_ids: set[str] = set()
        for it in reviewed:
            src = Path(it.get("file", ""))
            if not src.exists():
                continue
            dst = archive_dir / src.name
            try:
                src.rename(dst)
                archived_ids.add(it.get("id", ""))
            except Exception as e:
                self._set_action(f"failed to archive {src.name}: {e}", False)
                return
        if archived_ids:
            self.dismissed |= archived_ids
            save_dismissed(self.state_path, self.dismissed)
        self._set_action(f"archived {len(archived_ids)} item(s)", True)
        self.refresh()

    def _clipboard(self, text: str):
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update_idletasks()
            return True
        except Exception:
            return False
