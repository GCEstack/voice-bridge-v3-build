# SOP — Approved-Agent File Routing (production)

**Purpose:** How a file you drop into the shared outbox gets routed to the correct
agent's INBOX, via a spoken "approved" ping. This is the production version of the
simple send/ping test.

---

## 1. The boxes

| Box | Path | Role |
|-----|------|------|
| **Frozen copy (held by you)** | wherever you keep the master | The final, locked file you won't touch. |
| **Outbox (shared)** | `C:\Users\GCE_Outbox` | You drop files here. Everyone reads from here. |
| **Agent INBOX** | `...\GCE_PROD_Applied\GCE_PROD_<Agent>\INBOX` | Incoming work for that agent. |
| **Agent OUTBOX** | `...\GCE_PROD_Applied\GCE_PROD_<Agent>\OUTBOX` | Finished work the agent returns. |

---

## 2. The approved-agent ping (wake phrases)

Say **any one** of these to route a file to that agent:

| You say | Agent | Destination INBOX |
|---------|-------|-------------------|
| **"Deepseek approved"** | Deepseek | `GCE_PROD_Applied\GCE_PROD_Deepseek\INBOX` |
| **"Plumb approved"** | Plumb (Kimi Code) | `GCE_PROD_Applied\GCE_PROD_Plumb\INBOX` |
| **"Keel approved"** | Keel | `GCE_PROD_Applied\GCE_PROD_Keel\INBOX` |
| **"Kimi"** | Kimi | `GCE_PROD_Applied\GCE_PROD_Kimi\INBOX` |

The ping happens **through a status-bar ping** — the bridge watches for the approved
name, you get pinged, and the agent acts.

---

## 3. The routing loop (what happens on a ping)

1. **You hold** the final frozen copy (the master you won't touch).
2. **You drop** a file into `C:\Users\GCE_Outbox` (or route directly off the frozen copy).
3. **You speak** an approved agent name (e.g. "Keel approved").
4. **Ping fires** via the status bar — the target agent is notified.
5. **Agent picks up** the file and **copies** it into its own `INBOX`.
6. **Agent works** on it; if it has **questions**, it flags them in chat first.
7. **Agent returns** the finished result to its **OUTBOX** and reports back.

**Rule:** the shared outbox file is *copied*, never *moved* — so two agents can pick up
the same file if you name two agents, and your frozen copy is never touched.

---

## 4. Use case to test (first run)

**Scenario:** "Route a file to Keel by voice."

1. You drop `job-notes.txt` into `C:\Users\GCE_Outbox`.
2. You speak: **"Keel approved."**
3. Status-bar ping fires; Keel is notified.
4. Keel copies `job-notes.txt` → `GCE_PROD_Keel\INBOX\job-notes.txt`.
5. Confirmation in chat.

**Pass =** file appears in `GCE_PROD_Keel\INBOX\` *and* the copy still exists in the
outbox.

---

## 5. Current gaps to sign off (do not auto-create)

- Only `GCE_PROD_Keel` has an `INBOX` folder today.
- `GCE_PROD_Plumb` has **no INBOX** folder yet.
- `GCE_PROD_Deepseek` and `GCE_PROD_Kimi` **don't exist** as folders.
- **No agent has an `OUTBOX` folder yet** (you said you'd make them).

**Decision needed (yours):**
- (a) Create the missing INBOX + OUTBOX folders now so all agents can receive and return files, or
- (b) Only wire the agents that already have folders, or
- (c) Different agent names than I listed — tell me the exact roster.

---

## 6. Test checklist

- [ ] Drop file in outbox, speak "Keel approved" → file lands in Keel INBOX.
- [ ] Repeat for each agent folder that exists.
- [ ] Confirm outbox copy is NOT deleted after routing.
- [ ] Confirm agent returns finished work to its **OUTBOX**.
- [ ] Confirm status-bar ping actually fires and I report in chat.