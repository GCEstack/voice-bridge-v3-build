# VoiceBridge Baseline Dossier — 2026-09-30

## STEP 0.1 — TREE IDENTITY

**Working Tree:** `C:\Users\Dekan AI Brother\GCE_DON\voice-bridge\`  
**Entry Point:** `START-VOICEBRIDGE.cmd`  
**Python Version:** 3.14 (from `.venv\Scripts\python.exe`)  
**AssemblyAI Key Source:** `.env` file (`ASSEMBLYAI_API_KEY=b5a951d23eda48039571549f527b5c54`)

---

### Root Files (non-cache, non-venv)

| File | Purpose |
|------|---------|
| `.env` | AssemblyAI API key (kept in original location, NOT copied) |
| `.env.example` | Template for `.env` |
| `config.json` | Main configuration (hotkeys, wake words, STT model, queue settings) |
| `START-VOICEBRIDGE.cmd` | Launcher script |
| `voice-profile.json` | Voice profile settings |
| `queue_local.json` | Local queue state |
| `requirements.txt` | Python dependencies |
| `intent_audit.log` | Intent/cadence audit log (~574KB) |
| `intent_audit.log.1` | Rotated audit log (~2.7MB) |

### Directories

| Directory | Purpose |
|-----------|---------|
| `src/` | Python source code |
| `tests/` | Test suite |
| `queue/` | Handoff queue registry |
| `docs/` | Specification documents |
| `latest_logs/` | Runtime logs |
| `.venv/` | Python virtual environment (NOT copied) |
| `archived_logs/` | Old logs |

---

### Entry Point — START-VOICEBRIDGE.cmd

Contents:
```
@echo off
call .venv\Scripts\activate.bat
python src\voice_bridge.py
pause
```

Launches: `src/voice_bridge.py` in the `.venv` environment.

---

### Source Files (src/)

| File | Purpose |
|------|---------|
| `voice_bridge.py` | Main application (GUI, flow control) |
| `capture.py` | AssemblyAI v3 WebSocket STT capture |
| `intent.py` | Intent classification + cadence analysis — **DEFECT: 80-char truncation at line 102** |
| `llm.py` | LLM integration |
| `queue_panel.py` | Queue panel UI + refresh |
| `config.py` | Config loading |
| `voice_commands.py` | Voice command handlers |
| `voice_profile.py` | Voice profile management |
| `keyboard_input.py` | Keyboard input simulation |
| `screenshot.py` | Screenshot capture |

---

## STEP 0.2 — SNAPSHOT FOR RECOVERY

**Backup Location:** `C:\Users\Dekan AI Brother\GCE_DON\voice-bridge-baseline-20260930\`

**Files copied from original tree:** 81 files total  
**Snapshot Date:** 2026-09-30  
**Status:** COMPLETE

**SHA256 Hash Manifest (key files only):**

| Hash | File |
|------|------|
| `4E2CDD7BFD2A708BD352A7EEFC2DBE76D7122853DA356F6CA683FD8A08A3FE7A` | .env.example |
| `4A6872331C8F5E216E335665760A19C2699C2EEA7FBBBD2C5A1C5E3F56554110` | .gitignore |
| `20D07861610B2B4A8974C7686682CB6FF32CF5017BCBFC2284FB3BA3267BFFE3` | config.json |
| `6978C1BA5BBCD3A79DBEF4218509AE8E59DE58B59BB09464C98AFD5854E3CA97` | queue_local.json |
| `7B98564F889130406A4EC95951612F4F48AFE9886A1A2C1D60B82F47E34DA8B0` | README.md |
| `0294924D32DFE5D0A2329F472301055FA150B84BA4CFCE4547111110F306B666` | requirements.txt |
| `4DFD78D1DDAEB9797B1E641738AA7B2533E3CF1DEADAA97E373CD16BB2FDC9F5` | START-VOICEBRIDGE.cmd |
| `FCD7A6492A085D16D249EAB5652346276562C3D0CB87487D5C61CA945B7F0E3F` | voice-profile.json |
| `CCBD588832C7EC005C310F7CEE3E06B0AD3FFC4E4AE1BB9112234249A7F58DC4` | src/capture.py |
| `E4F74A2700F172E23340FB00E7CB8170AB1208DC4A6D3AD9F60EAEC9D36CCFF4` | src/config.py |
| `1EA8982A3587EFA630A45ACFEF8B90F139D8A7E8DA5AE9E0E5D085FAA3A796FC` | src/intent.py |
| `6421638C67496D79646119A144F26ED8FBE72CF88500E54A74F27C7848E55AC2` | src/voice_bridge.py |
| `24A277A40773BE13534233FAC031B8E3BB1AACA344593FABC937A28AFAD5F708` | src/queue_panel.py |

---

## STEP 0.3 — BASELINE BEHAVIOR CAPTURE

### Observed Runtime Behaviors

| Behavior | Location | Notes |
|----------|----------|-------|
| 80-char truncation | `src/intent.py:102` | `text[:80]` — THE defect G6 fixes |
| Dictation flow | `voice_bridge.py` | Capture → STT → Copy Text to clipboard |
| Queue panel read | `queue_panel.py` | Reads from `queue/` directory |
| Listening state | `capture.py` | AssemblyAI WebSocket streaming |
| Wake word detection | Config (`config.json`) | Wake words: "hey keel", "ok keel", "okay keel", "keel" |
| Health NOT observable | (old behavior) | Tier-3 watcher dead 4 days, said nothing — V3 fixes this |

---

## STEP 0.4 — FEATURE INVENTORY

### Buttons / Controls
- [ ] Mic toggle (on/off)
- [ ] Listening state indicator
- [ ] Queue panel (read-only display of handoffs)
- [ ] Dictation output (Copy Text to clipboard)
- [ ] Reconnect button
- [ ] Quit button

### Flows
- [ ] Wake word → activate listening
- [ ] Voice capture → STT → Copy Text
- [ ] Queue panel auto-refresh (reads `queue/` directory)
- [ ] VAD gate (silence detection)
- [ ] Reconnection on WebSocket drop

### External Calls
- [ ] AssemblyAI v3 WebSocket (STT)
- [ ] File system: `queue/` directory (read)
- [ ] Clipboard (write)
- [ ] Config: `config.json` (read)

### Known Defects (for parity)
- [ ] **80-char truncation at `intent.py:102`** (G6 fixes this)
- [ ] Health not observable (Tier-3 silent failure)

---

## DON CONFIRMATION REQUIRED

**Please confirm the feature inventory above matches your working experience.**

Specifically:
1. Are these all the buttons/controls you use?
2. Are these all the flows you follow?
3. Any features I missed?

Your confirmation = the spec. Nothing changes until you confirm.