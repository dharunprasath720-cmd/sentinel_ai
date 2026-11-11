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

## What it does not do

It does not show the PayPal Sandbox payment live (that needs your approval in a browser); a closing card says so. It does
not narrate. It records a headless browser, not your desktop.
