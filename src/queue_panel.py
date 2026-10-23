"""Don's session queue — completed work awaiting his decision.

REBUILT 2026-10-03 (Nico, Don authority: VoiceBridge queue plumbing reset).

WHAT THIS IS
    The one Don-facing surface for the target flow:

        model completes meaningful work
          -> one completion artifact
          -> ONE ingest
          -> one live queue item HERE
          -> Don chooses ARCHIVE or HANDOFF
          -> source item archived

WHAT THIS IS NOT
    Not a routing engine. Not a transport. Not a projection of 06_HANDOFFS,
    ai-inbox, an event ledger, or any seat lifecycle. It reads exactly one
    folder — the live queue inside this product tree — and it writes only
    through the two explicit actions below.

WHAT WAS REMOVED AND WHY
    * SILENT AGE ARCHIVAL (the reason the old queue was always empty).
      `_refresh()` used to archive anything older than "yesterday", every 30
      seconds, with no human action. That guarantee — that actionable work
      disappears on a timer — is gone. There is no timer, no age threshold and
      no background path to archiving anywhere in this module or in
      src/completion/store.py. Archive happens ONLY when Don presses ARCHIVE or
      a HANDOFF succeeds.
    * LEGACY COLUMN SET. from / to / status / source_type / drive_file_id are
      gone. Columns are the minimal contract: state, subject, source, time and
      the optional project.
    * DISMISSED-STATE. The old `dismissed` id list in queue_local.json is
      replaced by real archival: the item moves to archive/items/ and an event
      is recorded in state/archive_ledger.json, so history is preserved rather
      than hidden.

CONTRACT
    id          required   stable identity
    created_at  required   ISO-8601
    source      required   who produced it
    subject     required   one line
    artifact    required   path to the result
    state       required   outcome of the work
    project     optional
    workstream  optional

    Optional metadata is displayed when present and never gates visibility.
"""

from __future__ import annotations

import json
import os
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import messagebox, ttk

from src.completion.paths import queue_root
from src.completion.store import QueueStore

# Seat colors for the SOURCE column. Free text falls back to gray.
SEAT_COLORS = {
    "Nico": "#f97316",
    "Luce": "#a855f7",
    "Coda": "#3b82f6",
    "Chiave": "#14b8a6",
    "Falcon": "#22c55e",
    "Corrado": "#ef4444",
    "Vittorio": "#eab308",
    "Talon": "#92400e",
    "Keel": "#6b7280",
    "Don": "#d97706",
    "Enzo": "#06b6d4",
    "Serafina": "#d946ef",
}

DEFAULT_REFRESH_SECONDS = 30


# ---------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------
def normalize_record(m: dict, path: Path) -> dict:
    """Map one queue JSON onto the panel record. Missing fields degrade."""
    if not isinstance(m, dict):
        raise ValueError("record is not an object")
    artifact = str(m.get("artifact") or "")
    subject = str(m.get("subject") or "")
    if not subject:
        subject = Path(artifact).stem if artifact else path.stem
    return {
        "id": str(m.get("id") or path.stem),
        "created_at": str(m.get("created_at") or ""),
        "source": str(m.get("source") or "?"),
        "subject": subject[:120],
        "artifact": artifact,
        "state": str(m.get("state") or "-"),
        "project": str(m.get("project") or ""),
        "workstream": str(m.get("workstream") or ""),
        "content_key": str(m.get("content_key") or ""),
        "file": str(path),
    }


def format_human_time(iso_timestamp: str) -> str:
    if not iso_timestamp:
        return "-"
    try:
        dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
        now = datetime.now(dt.tzinfo)
        diff = now - dt
        if diff < timedelta(minutes=1):
            return "just now"
        if diff < timedelta(hours=1):
            return f"{int(diff.total_seconds() // 60)}m ago"
        if diff < timedelta(days=1):
            return f"{int(diff.total_seconds() // 3600)}h ago"
        if diff < timedelta(days=2):
            return "Yesterday"
        if diff < timedelta(days=7):
            return f"{diff.days}d ago"
        return dt.strftime("%b %d")
    except Exception:
        return "-"


def get_seat_color(seat: str) -> str:
    return SEAT_COLORS.get(seat, "#6b7280")


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


def open_artifact_folder(path: str) -> tuple[bool, str]:
    """Open Explorer at the SELECTED record's artifact directory."""
    if not path or not str(path).strip():
        return False, "no local artifact"
    p = Path(path)
    if not p.exists():
        return False, f"artifact no longer exists: {path}"
    folder = str(p.parent)
    try:
        os.startfile(folder)
        return True, folder
    except Exception as e:
        return False, str(e)


def record_text(rec: dict) -> str:
    """Clipboard payload: metadata header + the result body when readable."""
    body = ""
    art = Path(rec.get("artifact", ""))
    if art.exists() and art.is_file():
        try:
            body = art.read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            body = "(artifact could not be read)"
    lines = [
        f"id: {rec.get('id', '-')}",
        f"source: {rec.get('source', '?')}",
        f"state: {rec.get('state', '-')}",
        f"created_at: {rec.get('created_at', '-')}",
        f"artifact: {rec.get('artifact', '-')}",
    ]
    if rec.get("project"):
        lines.append(f"project: {rec['project']}")
    if rec.get("workstream"):
        lines.append(f"workstream: {rec['workstream']}")
    lines += ["", f"subject: {rec.get('subject', '-')}", "", body]
    return "\n".join(lines)


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
        tk.Label(self.tip_window, text=text, background="#fef9c3",
                 relief="solid", borderwidth=1, font=("Arial", 8)).pack()
        self.tip_window.update_idletasks()

    def _hide(self, _event=None):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


# ---------------------------------------------------------------------
# panel
# ---------------------------------------------------------------------
class QueuePanel(tk.Frame):
    """Don's queue: completed work awaiting his decision."""

    COLS = ("state", "subject", "source", "time", "project")
    WIDTHS = (("state", 66), ("subject", 250), ("source", 74),
              ("time", 62), ("project", 78))

    def __init__(self, master, config: dict):
        super().__init__(master)

        # Queue root resolves INSIDE the product tree. The legacy
        # handoff_queue.registry_path / local_state pair is deliberately NOT
        # read here: those pointed into the frozen voice-bridge tree, which is
        # exactly the split brain this reset removes.
        self.root_dir = queue_root()
        self.store = QueueStore(self.root_dir)

        hq = dict((config or {}).get("queue") or {})
        self.refresh_seconds = max(
            2.0, float(hq.get("refresh_seconds", DEFAULT_REFRESH_SECONDS) or
                       DEFAULT_REFRESH_SECONDS))

        self.show_archived = False
        self._all: list[dict] = []
        self._items: list[dict] = []

        self._build()
        self.refresh()
        self.after(int(self.refresh_seconds * 1000), self._auto_refresh)

    # -- UI ---------------------------------------------------------------
    def _build(self):
        head = tk.Frame(self)
        head.pack(fill="x")
        tk.Label(head, text="SESSION QUEUE", font=("Arial", 11, "bold")).pack(side="left")

        self.archived_var = tk.BooleanVar(value=False)
        view_frame = tk.Frame(head)
        view_frame.pack(side="right")
        self.active_btn = ttk.Radiobutton(view_frame, text="ACTIVE", variable=self.archived_var,
                                          value=False, command=self._toggle_archived)
        self.active_btn.pack(side="left")
        self.archived_radio = ttk.Radiobutton(view_frame, text="ARCHIVED",
                                               variable=self.archived_var,
                                               value=True, command=self._toggle_archived)
        self.archived_radio.pack(side="left")

        ttk.Button(head, text="Refresh", command=self.refresh, width=9).pack(side="right", padx=(8, 0))

        grid = tk.Frame(self)
        grid.pack(fill="both", expand=True, pady=(4, 4))
        grid.rowconfigure(0, weight=1)
        grid.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(grid, columns=self.COLS, show="headings", height=11)
        for col, width in self.WIDTHS:
            self.tree.heading(col, text=col.upper())
            self.tree.column(col, width=width, anchor="w")
        self.tree.tag_configure("completed", background="#fef3c7")
        self.tree.tag_configure("partial", background="#e0e7ff")
        self.tree.tag_configure("failed", background="#fee2e2")
        self.tree.tag_configure("blocked", background="#fee2e2")
        self.tree.tag_configure("archived", background="#e5e7eb")

        self.vscroll = ttk.Scrollbar(grid, orient="vertical", command=self.tree.yview)
        self.hscroll = ttk.Scrollbar(grid, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=self.vscroll.set,
                            xscrollcommand=self.hscroll.set)

        self.tree.grid(in_=grid, row=0, column=0, sticky="nsew")
        self.vscroll.grid(in_=grid, row=0, column=1, sticky="ns")
        self.hscroll.grid(in_=grid, row=1, column=0, sticky="ew")

        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-Button-1>", self._on_double_click)

        ToolTip(self.tree, lambda: (self._selected() or {}).get("created_at", ""))

        self.detail = tk.Text(self, height=5, wrap="word", state="disabled",
                              font=("Consolas", 9), background="#f8fafc")
        self.detail.pack(fill="x", pady=(0, 4))

        actions = tk.Frame(self)
        actions.pack(fill="x", pady=(0, 2))

        self.btn_handoff = ttk.Button(actions, text="HANDOFF", width=11,
                                      command=self._on_handoff)
        self.btn_handoff.pack(side="left", padx=2)

        self.btn_archive = ttk.Button(actions, text="ARCHIVE", width=11,
                                      command=self._on_archive)
        self.btn_archive.pack(side="left", padx=2)

        ttk.Separator(actions, orient="vertical").pack(side="left", fill="y", padx=6)

        util_frame = tk.Frame(actions)
        util_frame.pack(side="left")
        for label, fn, w in (
            ("Open", self._on_open, 10),
            ("Copy Text", self._on_copy_text, 11),
            ("Copy Path", self._on_copy_path, 11),
            ("Open folder", self._on_open_folder, 12),
        ):
            ttk.Button(util_frame, text=label, width=w, command=fn).pack(side="left", padx=1)

        self.action_status = tk.Label(self, text="", fg="#15803d", font=("Arial", 9))
        self.action_status.pack(anchor="w")
        self._set_action(
            f"queue: {self.root_dir}", True)

    # -- behavior ---------------------------------------------------------
    def refresh(self):
        """Re-read the live queue and re-render. READ-ONLY.

        There is no age filter here and there never will be again. An item
        leaves the active queue only through Don's ARCHIVE action or a
        successful HANDOFF.
        """
        try:
            self._all = self.store.archived() if self.show_archived else self.store.active()
        except Exception as e:
            self._all = []
            self._set_action(f"queue read failed: {e}", False)
            self._render()
            return
        self._render()

    def _auto_refresh(self):
        try:
            self.refresh()
        finally:
            self.after(int(self.refresh_seconds * 1000), self._auto_refresh)

    def _render(self):
        self.tree.delete(*self.tree.get_children())
        used: set[str] = set()
        for n, it in enumerate(self._all):
            rid = str(it.get("id") or "") or f"row-{n}"
            while rid in used:
                rid = f"{rid}-{n}"
            used.add(rid)
            tag = "archived" if self.show_archived else str(it.get("state", "-")).lower()
            self.tree.insert("", "end", iid=rid, values=(
                it.get("state", "-"),
                it.get("subject", "-"),
                it.get("source", "?"),
                format_human_time(it.get("created_at", "")),
                it.get("project", ""),
            ), tags=(tag,))
        archived_n = len(self.store.archived())
        self.archived_var.set(self.show_archived)
        if self.show_archived:
            self.active_btn.config(text=f"ACTIVE ({len(self.store.active())})")
            self.archived_radio.config(text=f"ARCHIVED ({archived_n})")
        else:
            self.active_btn.config(text=f"ACTIVE ({len(self.store.active())})")
            self.archived_radio.config(text=f"ARCHIVED ({archived_n})")
        self._show_detail(self._selected())

    def _toggle_archived(self):
        self.show_archived = bool(self.archived_var.get())
        self.refresh()

    def _show_detail(self, it):
        if not it:
            self._set_detail("")
            return
        lines = []
        lines.append(f"SUBJECT: {it.get('subject', '-')}")
        source = it.get('source', '?')
        state = it.get('state', '-')
        created = format_human_time(it.get('created_at', ''))
        lines.append(f"Source: {source}    State: {state}    {created}")
        if it.get("project"):
            lines.append(f"Project: {it['project']}")
        if it.get("workstream"):
            lines.append(f"Workstream: {it['workstream']}")
        artifact = it.get('artifact', '')
        if artifact:
            lines.append(f"Artifact: {artifact}")
        lines.append(f"ID: {it.get('id', '')}")

        body_preview = ""
        art = Path(it.get("artifact", ""))
        if art.exists() and art.is_file():
            try:
                body_text = art.read_text(encoding="utf-8", errors="replace")
                body_preview = body_text.strip()[:500]
            except OSError:
                pass
        if body_preview:
            lines.append("")
            lines.append("RESULT PREVIEW:")
            lines.append(body_preview)

        self._set_detail("\n".join(lines))

    def _set_detail(self, text):
        self.detail.config(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.config(state="disabled")

    def _set_action(self, text, ok):
        self.action_status.config(text=text, fg="#15803d" if ok else "#b91c1c")

    # -- selection ---------------------------------------------------------
    def _selected_id(self):
        sel = self.tree.selection()
        return str(sel[0]) if sel else ""

    def _selected(self):
        rid = self._selected_id()
        if not rid:
            return None
        for it in self._all:
            if str(it.get("id")) == rid:
                return it
        return None

    def _on_select(self, _event):
        self._show_detail(self._selected())

    def _on_double_click(self, _event):
        self._on_open()

    # -- read actions ------------------------------------------------------
    def _on_open(self):
        it = self._selected()
        if not it:
            self._set_action("select an item first", False)
            return
        ok, info = open_artifact(it.get("artifact", ""))
        self._set_action(("OPENED -> " if ok else "OPEN FAILED: ") + info, ok)

    def _on_open_folder(self):
        it = self._selected()
        if not it:
            self._set_action("select an item first", False)
            return
        ok, info = open_artifact_folder(it.get("artifact", ""))
        self._set_action(("opened folder -> " if ok else "FOLDER FAILED: ") + info, ok)

    def _on_copy_text(self):
        it = self._selected()
        if not it:
            self._set_action("select an item first", False)
            return
        self._clipboard(record_text(it))
        self._set_action(f"copied text for {it.get('id','')}", True)

    def _on_copy_path(self):
        it = self._selected()
        if not it:
            self._set_action("select an item first", False)
            return
        p = str(it.get("artifact", ""))
        if not p:
            self._set_action("record has no artifact path", False)
            return
        self._clipboard(p)
        self._set_action("copied path", True)

    def _clipboard(self, text):
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update_idletasks()
            return True
        except Exception:
            return False

    # -- Don actions -------------------------------------------------------
    def _on_archive(self):
        """ARCHIVE the selected item. Explicit, deliberate, reversible in intent.

        Moves the item to archive/items/ and records the event in the durable
        ledger. The source artifact is untouched. No age rule, no timer.
        """
        it = self._selected()
        if not it:
            self._set_action("select an item first", False)
            return
        if self.show_archived:
            self._set_action("already viewing archived items", False)
            return
        rid = str(it.get("id", ""))
        confirm = messagebox.askyesno(
            "Archive",
            f"Archive this result?\n\n"
            f"{it.get('subject','')}\n\n"
            "It leaves the active queue and is preserved in the archive.\n"
            "The result file itself is not deleted.")
        if not confirm:
            return
        res = self.store.archive(rid, reason="don: archive action")
        if not res.get("ok"):
            self._set_action(f"ARCHIVE FAILED: {res.get('error')}", False)
            return
        self.refresh()
        self._set_action(f"ARCHIVED {rid}", True)

    def _on_handoff(self):
        """HANDOFF the selected item: build a usable payload, then auto-archive.

        Payload is written and verified BEFORE the source is archived. On any
        failure the source stays active and the failure is shown — a queue item
        can never vanish without a usable copy existing.
        """
        it = self._selected()
        if not it:
            self._set_action("select an item first", False)
            return
        if self.show_archived:
            self._set_action("already viewing archived items", False)
            return
        rid = str(it.get("id", ""))
        confirm = messagebox.askyesno(
            "Handoff",
            f"Create a handoff copy of this result?\n\n"
            f"{it.get('subject','')}\n\n"
            "A handoff payload is written and verified, then this item\n"
            "is archived automatically.")
        if not confirm:
            return
        res = self.store.handoff(rid, recipient="")
        if not res.get("ok"):
            self._set_action(
                f"HANDOFF FAILED: {res.get('error')} "
                f"[source {res.get('source_state', 'unchanged')}]", False)
            return
        self.refresh()
        self._set_action(
            f"HANDOFF created -> {os.path.basename(res.get('payload_path',''))}; "
            f"source archived", True)