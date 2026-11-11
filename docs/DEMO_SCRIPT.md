# SENTINEL AI — demo script (about 4 minutes)

The story: a coordinated ring of accounts sharing devices starts paying the same merchants. SENTINEL sees it as it
happens, explains why, lets an analyst act, and is honest about what it cannot know.

Everything below was measured on the demo built by `python scripts/serve.py --rebuild` (seed 42, so it is the same
every time). Where a number was not measured, it says so.

## What the data does (so you know when to expect things)

The replay stream has 4,714 events (`SYN0010997` to `SYN0015710`).

| What | Where in the stream | Notes |
|---|---|---|
| Planted ring | first event at position **2,299** (`SYN0013296`), 57 ring events in total, spread over positions 2,299 to 4,323 | Across the 57 ring rows: accounts include `ACC_00345`, `ACC_00353`, `ACC_00128`, `ACC_00226`; the merchants are `M_0048` and `M_0062`; 10 distinct devices. Read the exact counts off the cluster you open |
| Legitimate but unusual | positions **427** (`SYN0011424`, $264.99), **1,732** (`SYN0012729`, $669.43), **2,671** (`SYN0013668`, $215.28) | Batch evaluation put all five such purchases at MONITOR. The levels of these three in the live replay were **not checked**: rehearse and look |
| Bursts (fraud and legitimate) | from position 55 on | Several accounts show fast repeat payments; some are legitimate |

**The catch.** The replay always starts at event 0, and in testing the live scorer handled roughly **3 events per
second** on this laptop (OneDrive folder, 7.9 GB RAM). Reaching the ring from a cold start would take about 13
minutes, so the demo needs a one-time warm-up (below). Events already scored are skipped as duplicates on a
second replay, which is fast.

## Before you record (once, about 25 minutes)

1. Close any old `serve.py`. Rebuild for a clean, repeatable demo (3 to 4 minutes; new demo passwords are written
   to `.env.demo`):
   ```
   .venv\Scripts\python scripts\serve.py --rebuild
   ```
2. Put `ANTHROPIC_API_KEY` in `.env` so the AI report and chat work. Check with `python scripts\check_env.py`.
3. Warm up. Sign in as `ana`, open **Live Monitoring**, set speed **1000** and limit **2290**, press **Start replay**,
   and wait until the Replay tile says 2,290 sent (about 13 minutes at 3 events per second; this is measured, not
   promised). This scores everything before the ring and leaves the ring for the recording.
4. Rehearse the ring once from here and note when the first HIGH rows arrive. Then **stop and rebuild again** if
   you want a pristine run, and repeat step 3. (Rebuilding resets everything, including the warm-up.)
5. For the PayPal scene (optional, needs your Sandbox keys in `.env`): start a tunnel
   (`cloudflared tunnel --url http://127.0.0.1:8000`), register `https://<tunnel>/paypal/webhook` in your Sandbox
   app for "Payment capture completed", put `PAYPAL_WEBHOOK_ID` in `.env`, restart `serve.py` with `--port 8000`
   without `--rebuild`, and have a Sandbox buyer account ready. A restarted tunnel changes the URL.
6. Install the Quincy CF or Astralaga font if you want the intended look; otherwise Georgia is used.
7. Browser at 100% zoom, a clean profile, notifications off, **`.env.demo` closed** (it holds passwords).

## The script

Times are targets. The recording can be edited; the two waits (replay, AI report) are the ones to cut.

### 0:00 Overview (30 s)
**Show:** sign in with the `ana` shortcut and the password from `.env.demo`. Land on Overview. Point at the tiles,
then the model panel.
**Say:** "SENTINEL scores every payment and explains the decision. This is the model's held-out quality: recall
next to precision, because accuracy would be meaningless at 2% fraud. It misses things, and the screen says so."
**Point out:** the Log scale toggle on the risk chart; clicking a level filters the list below.

### 0:30 Live monitoring (60 s)
**Show:** Live Monitoring. Press Start replay with speed **1000** and limit **2450**. The replay restarts from event
0, so the first 2,290 events are duplicates (already scored in the warm-up) and should be skipped within a few
seconds (not measured at this size); then about 160 new events arrive at the scorer's pace, roughly a minute.
Watch the feed, the p50 and p95 latency tiles, and the "events in the last 10 s" readout.
**Expect:** the first ring events (`SYN0013296` onwards) are likely LOW or MODERATE, because the shared-device
pattern does not exist yet. Once the cluster is flagged, ring rows turn HIGH or CRITICAL, pulse, and show
"Hold recommended".
**Say:** "The first ring payments look ordinary on their own. The pattern only exists once several accounts share
a device, and the system catches it from there. That is a real limit and I will not hide it. A hold is only
ever recommended, never executed."
**Measured earlier (full demo, not this exact run):** 19 of the 28 ring events in the live stream reached HIGH or
above (68%), 86% once the cluster was flagged; the first flag came at ring event number 8.

### 1:30 Graph Explorer (40 s)
**Show:** Graph Explorer, pick the newest flagged cluster, let the canvas settle, then click an account node to
pull in its neighbours.
**Say:** "Several accounts, a shared device, the same merchant, all within minutes" and read the actual counts from
the cluster you opened. "Border colour is risk, and every node also says its level in words. The explorer caps at
200 nodes and says when it cuts."

### 2:10 Investigation (60 s)
**Show:** press **Ctrl+K**, paste a ring transaction id that went HIGH (for example one from the feed), and press
Enter. Show the risk factors, the SHAP bars ("why the model scored it this way"), and the related accounts.
Select the alert, open a case, add a note, choose "Hold recommended" under Approve action and read the confirmation
aloud ("nothing is blocked automatically"). Press **Generate AI report**.
**Wait:** the report took about 50 seconds when measured. Narrate while it runs, or cut it.
**Say:** "The AI investigator only uses read-only tools, and every claim cites an id it actually retrieved. It says
suspicious, never fraud confirmed, and it lists what contradicts the story." Point at the "model-written" badge
and the contradictory evidence.

### 3:10 The innocent one (20 s)
**Show:** Ctrl+K and paste `SYN0011424` (position 427; present after the warm-up).
**Say:** "A $265 purchase far above this account's norm. It is flagged for attention, not called fraud." **Only say
this if the rehearsal showed MONITOR or REVIEW.** If it landed higher, say so and skip the line; do not edit the
story to fit.

### 3:30 A real PayPal payment (40 s, optional)
**Show:** run `.venv\Scripts\python scripts\paypal_sandbox_check.py`, open the approval link, approve as the Sandbox
buyer, press Enter. Switch the data source selector to PayPal Sandbox. The row `PP-…` appears on Live Monitoring.
**Say:** "A real Sandbox payment, signed by PayPal. We verify the signature with PayPal before trusting it, then score
it. It is low risk, which is right for a single normal payment. It carries no payer identity, so it is scored as its
own account instead of being merged into someone." 
**Be precise:** it was run once (one capture and one webhook); refunds exist in code but were never exercised.

### 3:50 Close (20 s)
**Say:** "Deterministic scoring, an AI that must show its evidence, and a human who decides. Honest limits: about a
fifth of planted fraud is missed, the data is synthetic, and PayPal is Sandbox only."

## If something goes wrong

| Symptom | Fix |
|---|---|
| Replay shows 0 processed | All events were duplicates (already scored). Use a higher limit, or `--rebuild` for a clean run |
| No ring HIGH rows after the warm-up | You are before position 2,299. Check the Replay tile's "sent" count |
| AI report or chat errors | Check `ANTHROPIC_API_KEY`; chat returns 503 without it, 502 on a provider failure; reports fall back to the deterministic version |
| PayPal row never appears | Tunnel URL changed, `PAYPAL_WEBHOOK_ID` missing, or `serve.py` not restarted after adding it. The startup line should say "PayPal Sandbox: configured" |
| Graph looks empty | Pick a cluster first; with no flagged cluster the list says so |

## Claims to avoid

- "Detects fraud" without "suspicious": nothing in SENTINEL confirms fraud.
- "Production ready": it is a hackathon demo on synthetic data, SQLite and a Sandbox.
- "Fully integrated with PayPal": order, capture and one signed webhook were exercised in Sandbox; refunds were not.
- Any recall or precision figure as a headline without the other and the caveat.
