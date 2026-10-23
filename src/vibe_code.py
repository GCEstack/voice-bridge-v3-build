"""Vibe Code — lightweight question/answer text documents for Don.

A "Vibe Code" document is a quick, informal text file where Don types or
speaks answers to questions. Unlike a formal handoff artifact, it is a personal
scratchpad: interview prep, implementation ledgers, claims to defend, quick
notes, talking points.

The panel (VibeCodePanel) provides:
  - Document list (left) — browse .md/.txt/.vibe files in the vibe_code/ dir
  - Text editor (right) — type or speak answers here (focus for dictation)
  - New / Save / Open / Open Folder / Focus for dictation
  - Template support for structured Q&A documents
  - Question navigation: parse Q: lines and jump between them

The voice bridge types into whatever window is focused, so clicking in the
editor and speaking is all it takes — no special wiring needed.

Pure helpers below are testable without Tkinter.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
import tkinter as tk

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_DIR_NAME = "vibe_code"
SUPPORTED_EXTENSIONS = (".md", ".txt", ".vibe")
DEFAULT_EXTENSION = ".md"


def vibe_root() -> Path:
    """Resolve the Vibe Code document directory.

    Reads from config if available, otherwise defaults to ``vibe_code/``
    relative to the current working directory (the project root).
    """
    try:
        from src.config import load_config
        cfg = load_config("config.json")
        vc = (cfg.get("vibe_code") or {})
        d = vc.get("directory")
        if d:
            return Path(d)
    except Exception:
        pass
    return Path(DEFAULT_DIR_NAME)


def _ensure_dir(directory: Path | None = None) -> Path:
    d = Path(directory) if directory is not None else vibe_root()
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
TEMPLATES: dict[str, str] = {
    "Blank": "",
    "Q&A Ledger": """# Vibe Code: {title}

**Date:** {date}
**Status:** in-progress

## Questions

Q: What is the main topic or claim you need to address?

A:

Q: What evidence or source supports it?

A:

Q: What are the key talking points?

A:

""",
    "Interview Prep": """# Vibe Code: {title}

**Date:** {date}
**Purpose:** Interview preparation notes
**Status:** in-progress

## Claims to Defend

### Claim 1
**Claim:**
**Evidence:**
**Status:** unverified

### Claim 2
**Claim:**
**Evidence:**
**Status:** unverified

## Talking Points

-
-
-

## Questions to Answer

Q:

A:

""",
    "Implementation Ledger": """# Vibe Code: {title}

**Date:** {date}
**Purpose:** Track implementations / engagements

## Ledger (fill one row per engagement)

| # | Client/Project | Industry | Modules | Role | Start | Go-Live | Stabilization | Full-cycle? | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 1 |  |  |  |  |  |  |  |  |  |
| 2 |  |  |  |  |  |  |  |  |  |
| 3 |  |  |  |  |  |  |  |  |  |
| 4 |  |  |  |  |  |  |  |  |  |
| 5 |  |  |  |  |  |  |  |  |  |

## Counting Rules
1. Full-cycle = led/participated from requirements through go-live AND stabilization.
2. Acquisition cutover counts only if you stood up the new entity end-to-end.
3. Rescue/reimplementation counts only if it reached go-live under your ownership.
4. Phases of one program count as ONE unless scope was genuinely separate go-lives.

## Claims to Defend

Q: How many full-cycle implementations?
A:

Q: Which ones are you most confident about?
A:

""",
    "Quick Notes": """# Vibe Code: {title}

**Date:** {date}

## Notes

-
-
-

## Action Items

- [ ]
- [ ]

""",
}


def template_names() -> list[str]:
    return list(TEMPLATES.keys())


def render_template(name: str, title: str = "Untitled") -> str:
    """Render a template with the given title and today's date."""
    tmpl = TEMPLATES.get(name, "")
    date = datetime.now().strftime("%Y-%m-%d")
    try:
        return tmpl.format(title=title, date=date)
    except (KeyError, IndexError):
        return tmpl


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def slugify(name: str) -> str:
    """Convert a free-text name to a safe filename stem."""
    name = (name or "").strip()
    if not name:
        return "untitled"
    # Replace path separators and dangerous chars
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = re.sub(r"\s+", "_", name)
    name = name.strip("._")
    return name or "untitled"


def list_documents(directory: Path | str | None = None) -> list[Path]:
    """List Vibe Code documents in the given directory (sorted by mtime desc)."""
    d = Path(directory) if directory is not None else vibe_root()
    if not d.exists() or not d.is_dir():
        return []
    files = []
    for p in d.iterdir():
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
            files.append(p)
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def read_document(path: Path | str) -> str:
    """Read a document's text content."""
    p = Path(path)
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def save_document(path: Path | str, content: str) -> Path:
    """Write content to a document path. Returns the path."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def create_document(directory: Path | str | None = None, name: str = "Untitled",
                   template: str = "Blank") -> Path:
    """Create a new Vibe Code document from a template. Returns the path."""
    d = _ensure_dir(directory)
    stem = slugify(name)
    ext = DEFAULT_EXTENSION
    path = d / f"{stem}{ext}"
    # Avoid overwriting: append counter if exists
    counter = 1
    while path.exists():
        path = d / f"{stem}_{counter}{ext}"
        counter += 1
    content = render_template(template, title=name)
    save_document(path, content)
    return path


def parse_questions(text: str) -> list[dict]:
    """Parse Q/A pairs from a document.

    Recognizes lines starting with 'Q:' or 'Q :' (case-insensitive).
    Each question collects following lines until the next Q: or blank section.
    Returns list of {index, question, answer, line_no}.
    """
    questions = []
    lines = text.splitlines()
    current_q = None
    current_answer_lines = []
    q_start = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        m = re.match(r"^Q\s*:\s*(.*)", stripped, re.IGNORECASE)
        if m:
            # Save previous question
            if current_q is not None:
                questions.append({
                    "index": len(questions),
                    "question": current_q,
                    "answer": "\n".join(current_answer_lines).strip(),
                    "line_no": q_start,
                })
            current_q = m.group(1).strip()
            current_answer_lines = []
            q_start = i
        elif current_q is not None:
            # Collect answer lines (skip leading 'A:' prefix)
            am = re.match(r"^A\s*:\s*(.*)", stripped, re.IGNORECASE)
            if am:
                current_answer_lines.append(am.group(1))
            elif stripped and not stripped.startswith("#"):
                current_answer_lines.append(line)
            # blank line ends answer collection for this question
            elif not stripped and current_answer_lines:
                # keep collecting but mark boundary
                current_answer_lines.append("")

    if current_q is not None:
        questions.append({
            "index": len(questions),
            "question": current_q,
            "answer": "\n".join(current_answer_lines).strip(),
            "line_no": q_start,
        })

    return questions


def count_words(text: str) -> int:
    """Count words in text."""
    return len(text.split()) if text.strip() else 0


# ---------------------------------------------------------------------------
# Tkinter panel
# ---------------------------------------------------------------------------
class VibeCodePanel(tk.Frame):
    """Don's Vibe Code panel — lightweight Q&A text documents."""

    def __init__(self, master, config: dict | None = None):
        super().__init__(master)
        self.config = config or {}
        self.doc_dir = _ensure_dir()
        self.current_path: Path | None = None
        self._dirty = False
        self._questions: list[dict] = []
        self._current_q = 0

        self._build()

    # -- UI ---------------------------------------------------------------
    def _build(self):
        # Header
        head = tk.Frame(self)
        head.pack(fill="x", pady=(4, 2))

        tk.Label(head, text="VIBE CODE", font=("Arial", 11, "bold")).pack(side="left", padx=(4, 8))

        btn_frame = tk.Frame(head)
        btn_frame.pack(side="right")

        for label, cmd, w in (
            ("New", self._on_new, 7),
            ("Save", self._on_save, 7),
            ("Open", self._on_open, 7),
            ("Folder", self._on_open_folder, 8),
            ("Focus", self._on_focus, 8),
        ):
            ttk.Button(btn_frame, text=label, width=w, command=cmd).pack(side="left", padx=1)

        # Main content: list (left) + editor (right)
        main = tk.PanedWindow(self, orient="horizontal", sashrelief="raised")
        main.pack(fill="both", expand=True, padx=4, pady=2)

        # Left: document list
        left = tk.Frame(main)
        main.add(left, width=180)

        tk.Label(left, text="Documents", font=("Arial", 9, "bold")).pack(anchor="w", padx=2)

        list_frame = tk.Frame(left)
        list_frame.pack(fill="both", expand=True)

        self.doc_listbox = tk.Listbox(list_frame, font=("Consolas", 9), selectmode="single")
        self.doc_listbox.pack(side="left", fill="both", expand=True)
        self.doc_listbox.bind("<<ListboxSelect>>", self._on_select_doc)
        self.doc_listbox.bind("<Double-Button-1>", lambda e: self._on_open_selected())

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.doc_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.doc_listbox.config(yscrollcommand=scrollbar.set)

        # Template selector below list
        tmpl_frame = tk.Frame(left)
        tmpl_frame.pack(fill="x", pady=(4, 0))
        tk.Label(tmpl_frame, text="Template:", font=("Arial", 8)).pack(anchor="w")
        self.tmpl_var = tk.StringVar(value="Blank")
        self.tmpl_combo = ttk.Combobox(tmpl_frame, textvariable=self.tmpl_var,
                                       values=template_names(), state="readonly", width=18)
        self.tmpl_combo.pack(fill="x")

        # Right: editor
        right = tk.Frame(main)
        main.add(right, width=500)

        # Question navigation bar (shown when questions parsed)
        self.q_nav_frame = tk.Frame(right)
        self.q_nav_frame.pack(fill="x", pady=(0, 2))

        self.q_label = tk.Label(self.q_nav_frame, text="", font=("Arial", 9, "bold"),
                                foreground="#1e40af")
        self.q_label.pack(side="left", padx=2)

        self.q_prev_btn = ttk.Button(self.q_nav_frame, text="< Prev", width=7,
                                     command=self._q_prev)
        self.q_prev_btn.pack(side="right", padx=1)
        self.q_next_btn = ttk.Button(self.q_nav_frame, text="Next >", width=7,
                                     command=self._q_next)
        self.q_next_btn.pack(side="right", padx=1)

        # Text editor
        editor_frame = tk.Frame(right)
        editor_frame.pack(fill="both", expand=True)

        self.editor = tk.Text(editor_frame, wrap="word", font=("Consolas", 10),
                              undo=True, background="#fafafa")
        self.editor.pack(side="left", fill="both", expand=True)

        editor_scroll = ttk.Scrollbar(editor_frame, orient="vertical", command=self.editor.yview)
        editor_scroll.pack(side="right", fill="y")
        self.editor.config(yscrollcommand=editor_scroll.set)

        # Bind dirty tracking
        self.editor.bind("<<Modified>>", self._on_modified)

        # Footer
        footer = tk.Frame(self)
        footer.pack(fill="x", pady=(2, 4))

        self.status_label = tk.Label(footer, text=f"dir: {self.doc_dir}",
                                     font=("Arial", 8), foreground="#6b7280")
        self.status_label.pack(side="left", padx=4)

        self.word_count_label = tk.Label(footer, text="0 words", font=("Arial", 8),
                                         foreground="#6b7280")
        self.word_count_label.pack(side="right", padx=4)

        # Question count
        self.q_count_label = tk.Label(footer, text="", font=("Arial", 8),
                                      foreground="#1e40af")
        self.q_count_label.pack(side="right", padx=4)

        # Initial load
        self._refresh_list()
        self._update_word_count()

    # -- behavior ---------------------------------------------------------
    def _set_status(self, text: str, ok: bool = True):
        color = "#15803d" if ok else "#b91c1c"
        self.status_label.config(text=text, foreground=color)

    def _refresh_list(self):
        self.doc_listbox.delete(0, "end")
        docs = list_documents(self.doc_dir)
        for p in docs:
            self.doc_listbox.insert("end", p.name)
        self._doc_paths = docs

    def _on_select_doc(self, _event=None):
        sel = self.doc_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx < len(self._doc_paths):
            path = self._doc_paths[idx]
            if self._dirty:
                if not messagebox.askyesno("Unsaved changes",
                                           "You have unsaved changes. Discard?"):
                    return
            self._load_document(path)

    def _load_document(self, path: Path):
        content = read_document(path)
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", content)
        self.current_path = path
        self._dirty = False
        self._parse_questions(content)
        self._set_status(f"loaded {path.name}", True)
        self._update_word_count()

    def _on_open_selected(self):
        sel = self.doc_listbox.curselection()
        if not sel:
            self._set_status("select a document first", False)
            return
        idx = sel[0]
        if idx < len(self._doc_paths):
            self._load_document(self._doc_paths[idx])

    def _on_new(self):
        # Ask for name
        name = self._prompt_name()
        if not name:
            return
        template = self.tmpl_var.get() or "Blank"
        try:
            path = create_document(self.doc_dir, name, template)
            self._refresh_list()
            self._load_document(path)
            self._set_status(f"created {path.name}", True)
        except Exception as e:
            self._set_status(f"create failed: {e}", False)

    def _prompt_name(self) -> str:
        # Simple dialog using tk.simpledialog
        import tkinter.simpledialog as sd
        return sd.askstring("New Vibe Code", "Document name:", parent=self) or ""

    def _on_save(self):
        if self.current_path is None:
            # Save as new
            name = self._prompt_name()
            if not name:
                return
            template = "Blank"
            path = self.doc_dir / f"{slugify(name)}{DEFAULT_EXTENSION}"
            counter = 1
            while path.exists() and path != self.current_path:
                path = self.doc_dir / f"{slugify(name)}_{counter}{DEFAULT_EXTENSION}"
                counter += 1
            self.current_path = path
        content = self.editor.get("1.0", "end-1c")
        try:
            save_document(self.current_path, content)
            self._dirty = False
            self._parse_questions(content)
            self._refresh_list()
            self._set_status(f"saved {self.current_path.name}", True)
        except Exception as e:
            self._set_status(f"save failed: {e}", False)

    def _on_open(self):
        # Open a file via dialog
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            parent=self,
            initialdir=str(self.doc_dir),
            filetypes=[("Vibe Code", "*.md *.txt *.vibe"),
                       ("All files", "*.*")],
        )
        if not path:
            return
        if self._dirty:
            if not messagebox.askyesno("Unsaved changes", "Discard unsaved changes?"):
                return
        self._load_document(Path(path))

    def _on_open_folder(self):
        folder = str(self.doc_dir)
        try:
            os.startfile(folder)
            self._set_status(f"opened folder -> {folder}", True)
        except Exception as e:
            self._set_status(f"folder failed: {e}", False)

    def _on_focus(self):
        """Focus the editor for dictation (voice bridge types here)."""
        self.editor.focus_set()
        self._set_status("editor focused — speak now", True)

    def _on_modified(self, _event=None):
        if self.editor.edit_modified():
            self._dirty = True
            self.editor.edit_modified(False)
            self._update_word_count()

    def _update_word_count(self):
        text = self.editor.get("1.0", "end-1c")
        wc = count_words(text)
        self.word_count_label.config(text=f"{wc} words")

    # -- Question navigation -----------------------------------------------
    def _parse_questions(self, text: str):
        self._questions = parse_questions(text)
        self._current_q = 0
        if self._questions:
            self.q_count_label.config(text=f"{len(self._questions)} questions")
            self._show_question(0)
        else:
            self.q_count_label.config(text="")
            self.q_label.config(text="")

    def _show_question(self, idx: int):
        if not self._questions:
            return
        idx = max(0, min(idx, len(self._questions) - 1))
        self._current_q = idx
        q = self._questions[idx]
        self.q_label.config(text=f"Q{idx + 1}: {q['question'][:80]}")
        # Highlight the question line in the editor
        try:
            line = q["line_no"] + 1
            self.editor.tag_remove("highlight", "1.0", "end")
            self.editor.tag_add("highlight", f"{line}.0", f"{line}.0 lineend")
            self.editor.tag_config("highlight", background="#fef08a")
            self.editor.see(f"{line}.0")
        except Exception:
            pass

    def _q_prev(self):
        if self._questions and self._current_q > 0:
            self._show_question(self._current_q - 1)

    def _q_next(self):
        if self._questions and self._current_q < len(self._questions) - 1:
            self._show_question(self._current_q + 1)

    # -- public helpers ----------------------------------------------------
    def get_text(self) -> str:
        return self.editor.get("1.0", "end-1c")

    def set_text(self, text: str):
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", text)
        self._dirty = True
        self._parse_questions(text)
        self._update_word_count()
