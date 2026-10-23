"""Headless tests for the Vibe Code module (pure helpers + templates).

No Tkinter root is created here — only the pure helpers are exercised.
"""

import os
import tempfile
from pathlib import Path

import src.vibe_code as vc
from src.vibe_code import (
    slugify,
    list_documents,
    read_document,
    save_document,
    create_document,
    parse_questions,
    count_words,
    template_names,
    render_template,
    TEMPLATES,
    SUPPORTED_EXTENSIONS,
)


ROOT = Path(__file__).resolve().parents[1]


def test_slugify_basic():
    assert slugify("My Document") == "My_Document"
    assert slugify("") == "untitled"
    assert slugify("  ") == "untitled"
    assert slugify("a/b\\c") == "abc"
    assert slugify("Hello World! 123") == "Hello_World!_123"


def test_slugify_dangerous_chars():
    assert slugify('file<>:"/\\|?*name') == "filename"
    assert slugify("...dots...") == "dots"


def test_list_documents_empty(tmp_path):
    assert list_documents(tmp_path) == []


def test_list_documents_filters_extensions(tmp_path):
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    (tmp_path / "b.txt").write_text("world", encoding="utf-8")
    (tmp_path / "c.py").write_text("code", encoding="utf-8")
    (tmp_path / "d.vibe").write_text("vibe", encoding="utf-8")
    docs = list_documents(tmp_path)
    names = [p.name for p in docs]
    assert "a.md" in names
    assert "b.txt" in names
    assert "d.vibe" in names
    assert "c.py" not in names


def test_list_documents_sorted_by_mtime(tmp_path):
    import time
    (tmp_path / "old.md").write_text("old", encoding="utf-8")
    time.sleep(0.05)
    (tmp_path / "new.md").write_text("new", encoding="utf-8")
    docs = list_documents(tmp_path)
    assert docs[0].name == "new.md"


def test_list_documents_nonexistent():
    assert list_documents("/nonexistent/path/xyz") == []


def test_read_document(tmp_path):
    p = tmp_path / "test.md"
    p.write_text("hello world", encoding="utf-8")
    assert read_document(p) == "hello world"


def test_read_document_missing():
    assert read_document("/nonexistent/file.md") == ""


def test_save_document(tmp_path):
    p = tmp_path / "out.md"
    save_document(p, "saved content")
    assert p.read_text(encoding="utf-8") == "saved content"


def test_save_document_creates_parent(tmp_path):
    p = tmp_path / "sub" / "dir" / "out.md"
    save_document(p, "nested")
    assert p.read_text(encoding="utf-8") == "nested"


def test_create_document_blank(tmp_path):
    path = create_document(tmp_path, "My Doc", "Blank")
    assert path.exists()
    assert path.name == "My_Doc.md"
    assert read_document(path) == ""


def test_create_document_with_template(tmp_path):
    path = create_document(tmp_path, "Test Ledger", "Q&A Ledger")
    content = read_document(path)
    assert "Test Ledger" in content
    assert "Q:" in content
    assert "A:" in content


def test_create_document_no_overwrite(tmp_path):
    p1 = create_document(tmp_path, "Dup", "Blank")
    p2 = create_document(tmp_path, "Dup", "Blank")
    assert p1 != p2
    assert p2.name == "Dup_1.md"


def test_parse_questions_basic():
    text = "Q: What is your name?\nA: Don\n\nQ: What do you do?\nA: NetSuite consulting"
    qs = parse_questions(text)
    assert len(qs) == 2
    assert qs[0]["question"] == "What is your name?"
    assert qs[0]["answer"] == "Don"
    assert qs[1]["question"] == "What do you do?"
    assert qs[1]["answer"] == "NetSuite consulting"


def test_parse_questions_no_answers():
    text = "Q: First question?\n\nQ: Second question?"
    qs = parse_questions(text)
    assert len(qs) == 2
    assert qs[0]["answer"] == ""
    assert qs[1]["answer"] == ""


def test_parse_questions_empty():
    assert parse_questions("") == []
    assert parse_questions("No questions here.") == []


def test_parse_questions_case_insensitive():
    text = "q: lowercase question?\na: answer here"
    qs = parse_questions(text)
    assert len(qs) == 1
    assert qs[0]["question"] == "lowercase question?"


def test_parse_questions_multiline_answer():
    text = "Q: Describe your experience.\nA: Line one.\nLine two.\nLine three."
    qs = parse_questions(text)
    assert len(qs) == 1
    assert "Line one." in qs[0]["answer"]
    assert "Line two." in qs[0]["answer"]


def test_count_words():
    assert count_words("") == 0
    assert count_words("hello world") == 2
    assert count_words("  spaces   everywhere  ") == 2


def test_template_names():
    names = template_names()
    assert "Blank" in names
    assert "Q&A Ledger" in names
    assert "Interview Prep" in names
    assert "Implementation Ledger" in names
    assert "Quick Notes" in names


def test_render_template():
    content = render_template("Q&A Ledger", title="Test Doc")
    assert "Test Doc" in content
    assert "Q:" in content


def test_render_template_blank():
    assert render_template("Blank", title="X") == ""


def test_render_template_unknown():
    # Unknown template returns empty string
    result = render_template("Nonexistent", title="X")
    assert result == ""


def test_templates_have_required_keys():
    for name, tmpl in TEMPLATES.items():
        # All templates should be strings
        assert isinstance(tmpl, str)


def test_vibe_root_default():
    # Should return a Path
    root = vc.vibe_root()
    assert isinstance(root, Path)


def test_supported_extensions():
    assert ".md" in SUPPORTED_EXTENSIONS
    assert ".txt" in SUPPORTED_EXTENSIONS
    assert ".vibe" in SUPPORTED_EXTENSIONS
