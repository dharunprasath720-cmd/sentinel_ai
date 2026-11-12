# Demo video recorder

A scripted, captioned screen recording of the SENTINEL dashboard. It drives the real app in headless Chromium
(Playwright), burns captions and a visible cursor into the page, records video, speeds up the dead waits (the replay and
the AI report) and encodes an MP4. There is no narration and no music.

It is a development tool, not part of the app, and has its own `package.json`.

## Run it

1. Build a **clean** demo in its own folder (so your real `demo.db` is untouched) and serve it on port 8001:
   ```
   python scripts\serve.py --home <demo-folder> --port 8001 --rebuild
   ```
   A recording changes the demo (it creates a case and scores events), so for another take, copy the clean folder
   first and serve the copy, or rebuild.
2. Install the recorder once:
   ```
   cd demo-video
   npm install
   npx playwright install chromium     # about 200 MB, cached outside the repo
   ```
3. You need an `ffmpeg` binary. `pip install imageio-ffmpeg` in any Python environment provides one
   (`imageio_ffmpeg.get_ffmpeg_exe()` prints its path).
4. Record:
   ```
   set BASE=http://127.0.0.1:8001
   set DEMO_HOME=<demo-folder>
   set FFMPEG=<path to ffmpeg.exe>
   node record.mjs
   ```
   Output goes to `out/` (git-ignored): `sentinel-demo.mp4`, the raw `demo-raw.webm`, `waits.json` and checkpoint
   screenshots in `out/frames/`. `FAST=1` shortens every pause, for debugging the script.

## What it needs and uses

- `ANTHROPIC_API_KEY` in the repo's `.env` for the AI-report scene (one real Claude call, a few cents). Without it the
  report falls back to the deterministic version and the caption will be wrong, so set it.
- The login password is read from `DEMO_HOME/.env.demo` at run time and typed into a masked field. It is never logged.

## Length and the PayPal scene

The hackathon rule is a video under 3 minutes. The script fails (exit code 2) if the encoded MP4 is 175 seconds or longer;
lower `SCALE` (the caption dwell multiplier, default 0.8) and record again.

The PayPal scene shows a payment that is already in the demo database: it switches the data source to PayPal Sandbox and
opens the `PP-…` row. It cannot make a new payment (that needs a buyer's approval in a browser), so the caption says the
payment was received earlier. A freshly built demo has no PayPal row; either send a real Sandbox payment to it first
(`scripts/paypal_sandbox_check.py` with the webhook configured), or the scene falls back to a card that says the payment is
not shown.

## What it does not do

It does not narrate, and it records a headless browser, not your desktop.
