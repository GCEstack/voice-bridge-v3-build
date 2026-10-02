# SOP — Send Files & Ping (user-to-agent workflow)

**Purpose:** A simple, repeatable procedure for how you (the user) hand files to me and
ping me to act, so we can test the flow before scaling it to other users.

**Scope:** First pass. Keep it dead simple — one way to send, one way to ping, one place
to watch for results.

---

## 1. How to SEND a file to me

**Do ONE of these (pick per test):**

| Method | How | Best for |
|--------|-----|----------|
| **Inbox drop** | `inbox` → drop message, attach/point to file path | Text, short notes, pointers to a file |
| **Folder drop** | Put the file into `C:\Users\Dekan AI Brother\GCE_DON\voice-bridge\docs\inbox\` | Actual files you want read verbatim |
| **Voice path** | Dictate a pointer ("it's in <path>") and I go read it | When you're hands-free |

**Rule:** tell me the **file path** (or drop it in the inbox folder). Don't paste a whole
file into chat if you can give me a path — I read it directly.

---

## 2. How to PING me to act

A ping is just: a clear, short signal that says **"this is now the thing I want done."**

- **Best ping:** one line, imperative, names the output.
  - "Process the file in inbox and summarize it."
  - "Review `config.json` and report what changed."
- **Wake word ping (voice):** say the wake word, then give the instruction.
- **No-message ping:** if you just drop a file with no instruction, I assume
  `read it, tell me what it is, and flag anything urgent` — I do NOT auto-edit/act on it.

**Rule:** a ping without an instruction = *read and report only*. To make me *do* something,
you must say the action.

---

## 3. What I do after a ping (standard loop)

1. **Acknowledge** — you get a short "got it, on <X>".
2. **Read** the file (from path or inbox folder).
3. **Do** the action stated (or report-only if no action stated).
4. **Reply in chat** with the result + file location of any output.
5. **Log** it so the flow is testable and repeatable.

---

## 4. Use case to test (first run)

**Scenario:** "Send a file and get a summary."

1. You put `sample.txt` into `docs\inbox\`.
2. You ping: `"Read sample.txt and give me a 3-bullet summary."`
3. I read it, reply with 3 bullets, and confirm the path I read from.
4. **Pass =** the summary matches the file, and I cited the right path.

**Second use case:** "Ping to act, no file."
1. You ping: `"Draft an SOP for sending files (this doc)."`
2. I create the doc, tell you where it is, and wait for your sign-off.

---

## 5. Test checklist (run these in order)

- [ ] Drop a file in `docs\inbox\`, ping report-only → confirm I read the right path.
- [ ] Ping with an action (no file) → confirm I act and name the output location.
- [ ] Voice: wake word + instruction → confirm it types into the focused window.
- [ ] Confirm every result shows up in chat (nothing "just happens" silently).

---

## 6. Failure / no-response

- **No reply in ~1 min:** ping again with the file path spelled out.
- **Wrong file read:** you gave a path I can't see — re-drop into `docs\inbox\` and re-ping.
- **Voice typed to wrong window:** click the target box first, then dictate.

---

## 7. What I will NOT do without your sign-off

- Auto-edit a file from a report-only ping.
- Act on a dropped file with no instruction.
- Rename/re-brand anything (naming decisions are yours).