import json
import os
import tempfile

from src.config import load_config, DEFAULT_CONFIG


def test_default_config_has_required_keys():
    keys = [
        "dictation_hotkey",
        "mic_device",
        "assemblyai_api_key",
        "speech_model",
        "keyterms",
        "sample_rate",
        "channels",
    ]
    for key in keys:
        assert key in DEFAULT_CONFIG


def test_load_config_reads_file():
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f:
        json.dump({"mic_device": "usb"}, f)
        path = f.name
    try:
        cfg = load_config(path)
        assert cfg["mic_device"] == "usb"
        assert cfg["dictation_hotkey"] == "ctrl+shift+space"
    finally:
        os.unlink(path)


def test_load_config_missing_file_uses_defaults():
    cfg = load_config("does_not_exist.json")
    # Every default key is present with its default value...
    for key, value in DEFAULT_CONFIG.items():
        if key == "keyterms":
            continue  # wake words are merged into keyterms (see below)
        assert cfg[key] == value
    # ...and the default wake words are merged into keyterms (Title Cased) so the
    # AssemblyAI engine recognizes them via keyterms_prompt.
    for term in ("Hey Keel", "Ok Keel", "Okay Keel", "Keel"):
        assert term in cfg["keyterms"]
