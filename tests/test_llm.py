from unittest.mock import patch

from src.llm import _clean_output, rewrite_text


def test_clean_output_strips_bullets_and_hints():
    raw = (
        "kimi version 0.39.1\n"
        "\u2022 I want to go to the store tomorrow and buy some things\n"
        "\n"
        "To resume this session: kimi -r abc123\n"
    )
    assert _clean_output(raw) == (
        "I want to go to the store tomorrow and buy some things"
    )


def test_clean_output_keeps_multiline_content():
    raw = "\u2022 First line\n\u2022 Second line\n"
    assert _clean_output(raw) == "First line\nSecond line"


@patch("src.llm.subprocess.run")
def test_rewrite_text_success(mock_run):
    import subprocess

    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="\u2022 Corrected text\n",
        stderr="",
    )
    assert rewrite_text("proofread", "some text") == "Corrected text"
    # prompt built from the proofread rule
    called = mock_run.call_args
    assert "fix spelling, grammar" in called.args[0][2]


@patch("src.llm.subprocess.run")
def test_rewrite_text_raises_on_nonzero_exit(mock_run):
    import subprocess
    import pytest

    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="boom"
    )
    with pytest.raises(RuntimeError):
        rewrite_text("concise", "text")


@patch("src.llm.subprocess.run")
def test_rewrite_text_raises_on_empty(mock_run):
    import subprocess
    import pytest

    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="\n\n", stderr=""
    )
    with pytest.raises(RuntimeError):
        rewrite_text("format", "text")