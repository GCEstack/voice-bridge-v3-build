import json
import os

DEFAULT_CONFIG = {
    "dictation_hotkey": "ctrl+shift+space",  # legacy, unused in wake-word mode
    "mode": "wake_word",  # "wake_word" (always-on, hands-free) | "push_to_talk" (legacy)
    # "continuous": when True, dictation types into the focused window with no
    # wake-word gate. Toggle from the bridge window ("Continuous" checkbox) or
    # set here. Default True so it "just types".
    "continuous": True,
    # Wake-word activation (hands-free). The mic is always listening via
    # AssemblyAI; nothing is typed until a finalized turn begins with one of
    # these phrases. After waking, dictation is typed until a sleep command or
    # the armed timeout elapses.
    "wake_words": ["hey keel", "ok keel", "okay keel", "keel"],
    "armed_timeout_seconds": 12.0,  # auto-sleep after this many seconds idle
    "mic_device": "default",
    "assemblyai_api_key": "",
    "speech_model": "universal-3-5-pro",
    "keyterms": [
        "Plumb", "GLM", "EC4", "EC8", "Plumb", "Claude", "Renzo", "Santonio",
    ],
    "sample_rate": 16000,
    "channels": 1,
    # Local silence gate (VAD-lite). Audio is only sent upstream while the
    # mic level is at/above vad_threshold (RMS of int16) or within
    # vad_silence_seconds of the last loud chunk. 0 disables silence-hold.
    "vad_threshold": 500.0,
    "vad_silence_seconds": 3.0,
    # Auto-macro: after this many cumulative dictated characters, auto
    # select-all + proofread. Above auto_concise_after, chain proofread ->
    # concise -> send. 0 disables.
    "auto_proofread_after": 300,
    "auto_concise_after": 7000,
    # Reconnect cadence for the always-on AssemblyAI session (it auto-closes
    # after ~3h server-side; the supervisor brings it back on this interval).
    "supervisor_interval_seconds": 2.0,
}


def load_config(path: str) -> dict:
    if not os.path.exists(path):
        cfg = DEFAULT_CONFIG.copy()
    else:
        with open(path, "r", encoding="utf-8") as f:
            user = json.load(f)
        cfg = DEFAULT_CONFIG.copy()
        cfg.update(user)

    # Ensure the wake words are recognized by the engine: merge them into
    # keyterms (case-sensitive proper-noun forms) so AssemblyAI biases toward
    # them via keyterms_prompt. Cap at 100 per AssemblyAI's limit.
    wake = [w.strip() for w in cfg.get("wake_words", []) if w and w.strip()]
    if wake:
        existing = list(cfg.get("keyterms") or [])
        for w in wake:
            # Store as Title Case so the engine spells it capitalized.
            titled = " ".join(p.capitalize() for p in w.split())
            if titled not in existing:
                existing.append(titled)
        cfg["keyterms"] = existing[:100]
    return cfg
