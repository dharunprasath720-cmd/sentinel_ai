# SENTINEL AI — demo script (about 4 minutes)

The story: a coordinated ring of accounts sharing devices starts paying the same merchants. SENTINEL sees it as it
happens, explains why, lets an analyst act, and is honest about what it cannot know.

Everything below was measured on the demo built by `python scripts/serve.py --rebuild` (seed 42, so it is the same
every time). Where a number was not measured, it says so.

## What the data does (so you know when to expect things)

The replay stream has 4,714 events (`SYN0010997` to `SYN0015710`). The **Start at event** box on Live Monitoring
begins the replay part-way through; events before it are skipped, not scored.

| What | Where in the stream | Notes |
|---|---|---|
| Planted ring | first event at position **2,299** (`SYN0013296`), 57 ring events in total, spread over positions 2,299 to 4,323 | Across the 57 ring rows: accounts include `ACC_00345`, `ACC_00353`, `ACC_00128`, `ACC_00226`; the merchants are `M_0048` and `M_0062`; 10 distinct devices. Read the exact counts off the cluster you open |
| Legitimate but unusual | positions 427 (`SYN0011424`), 1,732 (`SYN0012729`), **2,671** (`SYN0013668`, $215.28) | `SYN0013668` was replayed and came out **MODERATE, action MONITOR**. The other two were not checked |
| Bursts (fraud and legitimate) | from position 55 on | Several accounts show fast repeat payments; some are legitimate |

**What the replay does from position 2,290** (the window 2,290 to 2,710, measured twice):
28 ring events: 3 LOW, 6 MODERATE, 19 HIGH, none CRITICAL. The cluster is flagged at ring event number 8. HIGH ring
rows are recommended **REVIEW**, and no hold appears in this window, because a hold needs a CRITICAL payment inside a
flagged cluster. 4 of 392 non-ring events reached HIGH. The same window gave nearly the same result when the
2,290 earlier events were scored first (28 ring events: 2 LOW, 7 MODERATE, 19 HIGH; flagged at event 8), so skipping
ahead does not change the story.

**Speed.** The scorer handled 5.7 to 6.0 events per second in-process on this laptop (OneDrive folder, 7.9 GB RAM).
Through the dashboard during testing it felt slower, about 3 per second, so allow for that. Starting at 2,290, the
first ring event is about 9 events in, and the cluster flag arrives a few seconds later.

## Before you record (once, about 10 minutes)

1. Close any old `serve.py`. Rebuild for a clean, repeatable demo (3 to 4 minutes; new demo passwords are written to
   `.env.demo`):
   ```
   .venv\Scripts\python scripts\serve.py --rebuild
   ```
   Do a **rehearsal replay** first if you want, then rebuild again: replays are saved, and a repeated window is
   skipped as already scored.
2. Put `ANTHROPIC_API_KEY` in `.env` so the AI report and chat work. Check with `python scripts\check_env.py`.
3. For the PayPal scene (optional, needs your Sandbox keys in `.env`): start a tunnel
   (`cloudflared tunnel --url http://127.0.0.1:8000`), register `https://<tunnel>/paypal/webhook` in your Sandbox
   app for "Payment capture completed", put `PAYPAL_WEBHOOK_ID` in `.env`, and restart `serve.py` (no `--rebuild`).
   Have a Sandbox buyer account ready. A restarted tunnel changes the URL.
4. Install the Quincy CF or Astralaga font if you want the intended look; otherwise Georgia is used.
5. Browser at 100% zoom, a clean profile, notifications off, **`.env.demo` closed** (it holds passwords).

## The script

Times are targets. The recording can be edited; the two waits (replay, AI report) are the ones to cut.

### 0:00 Overview (30 s)
**Show:** sign in with the `ana` shortcut and the password from `.env.demo`. Land on Overview. Point at the tiles,
then the model panel.
**Say:** "SENTINEL scores every payment and explains the decision. This is the model's held-out quality: recall
next to precision, because accuracy would be meaningless at 2% fraud. It misses things, and the screen says so."
**Point out:** the Log scale toggle on the risk chart; clicking a level filters the list below.

### 0:30 Live monitoring (70 s)
**Show:** Live Monitoring. Set **Start at event 2290**, **Limit 400**, speed 1000, and press Start replay. Watch the
feed, the p50 and p95 latency tiles, and the "events in the last 10 s" readout. This replays 400 events and should take
about one to two minutes (measured at 6 events per second; slower through the dashboard).
**Expect:** the first ring events (`SYN0013296` onwards) are likely LOW or MODERATE, because the shared-device
pattern does not exist yet. Around the eighth ring event the cluster is flagged, and ring rows turn HIGH, pulse, and
show **Review**. Roughly 380 events in, `SYN0013668` (the legitimate one) arrives as MODERATE.
**Say:** "The first ring payments look ordinary on their own. The pattern only exists once several accounts share
a device, and the system catches it from there. That is a real limit and I will not hide it. Every action here is a
recommendation; nothing is blocked automatically."

### 1:40 Graph Explorer (40 s)
**Show:** Graph Explorer, pick the newest flagged cluster, let the canvas settle, then click an account node to
pull in its neighbours.
**Say:** "Several accounts, a shared device, the same merchant, all within minutes" and read the actual counts from
the cluster you opened. "Border colour is risk, and every node also says its level in words. The explorer caps at
200 nodes and says when it cuts."

### 2:20 Investigation (60 s)
**Show:** press **Ctrl+K**, paste a ring transaction id that went HIGH (take one from the feed), and press Enter.
Show the risk factors, the SHAP bars ("why the model scored it this way"), and the related accounts. Select the
alert, open a case, add a note, choose "Hold recommended" under Approve action and read the confirmation aloud
("nothing is blocked automatically"). Press **Generate AI report**.
**Say about the action:** the system recommended REVIEW; the analyst is choosing to recommend a hold, which is the
human decision, and it only records the choice.
**Wait:** the report took about 50 seconds when measured. Narrate while it runs, or cut it.
**Say:** "The AI investigator only uses read-only tools, and every claim cites an id it actually retrieved. It says
suspicious, never fraud confirmed, and it lists what contradicts the story." Point at the "model-written" badge
and the contradictory evidence.

### 3:20 The innocent one (20 s)
**Show:** Ctrl+K and paste `SYN0013668`.
**Say:** "A purchase that is unusual for this account. It is rated MODERATE with the action MONITOR: flagged for
attention, not called fraud." This was measured twice; it is still worth glancing at the screen before saying it.

### 3:40 A real PayPal payment (40 s, optional)
**Show:** run `.venv\Scripts\python scripts\paypal_sandbox_check.py`, open the approval link, approve as the Sandbox
buyer, press Enter. Switch the data source selector to PayPal Sandbox. The row `PP-…` appears on Live Monitoring.
**Say:** "A real Sandbox payment, signed by PayPal. We verify the signature with PayPal before trusting it, then score
it. It is low risk, which is right for a single normal payment. It carries no payer identity, so it is scored as its
own account instead of being merged into someone."
**Be precise:** it was run once (one capture and one webhook); refunds exist in code but were never exercised.

### 4:20 Close (20 s)
**Say:** "Deterministic scoring, an AI that must show its evidence, and a human who decides. Honest limits: about a
fifth of planted fraud is missed, the data is synthetic, and PayPal is Sandbox only."

## If something goes wrong

| Symptom | Fix |
|---|---|
| Replay shows 0 processed | Those events were already scored (a repeated window is skipped). Pick a later **Start at event**, or `--rebuild` for a clean run |
| "offset … is beyond the … replay events" | **Start at event** must be 0 to 4,713 |
| No ring HIGH rows | Check **Start at event** is 2290 or earlier and **Limit** is large enough to reach about 2,320 |
| AI report or chat errors | Check `ANTHROPIC_API_KEY`; chat returns 503 without it, 502 on a provider failure; reports fall back to the deterministic version |
| PayPal row never appears | Tunnel URL changed, `PAYPAL_WEBHOOK_ID` missing, or `serve.py` not restarted after adding it. The startup line should say "PayPal Sandbox: configured" |
| Graph looks empty | Pick a cluster first; with no flagged cluster the list says so |

## Claims to avoid

- "Detects fraud" without "suspicious": nothing in SENTINEL confirms fraud.
- "Production ready": it is a hackathon demo on synthetic data, SQLite and a Sandbox.
- "Fully integrated with PayPal": order, capture and one signed webhook were exercised in Sandbox; refunds were not.
- "Holds the payment": a hold is a recommendation; none appears in the replay window used here.
- Any recall or precision figure as a headline without the other and the caveat.
