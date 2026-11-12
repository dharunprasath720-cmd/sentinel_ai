# Deploying the public demo on Render

The repository includes a `Dockerfile` and a `render.yaml` Blueprint. The image builds the dashboard, then builds the
synthetic demo world once (about a minute) and adds one real, verified PayPal Sandbox payment, so a cold start only has
to load it. Free plan, no card needed for the plan itself.

## Steps (about 10 minutes)

1. Sign in at https://render.com (GitHub login is easiest) and allow it to read the `sentinel_ai` repository.
2. **New > Blueprint**, choose the repository, branch `main`. Render reads `render.yaml` and shows one web service,
   `sentinel-ai`, on the free plan.
3. Leave the optional environment variables empty for now, and click **Apply**. The first build takes about 5 to 10
   minutes (installing the Python packages is the slow part).
4. When it says **Live**, open the `https://sentinel-ai-xxxx.onrender.com` address. Click the **ana** chip: the shared
   demo password fills in. Check Live Monitoring, start the replay, and open an alert.
5. Paste that address into the Devpost "demo link" field.

## What the public demo is

- Synthetic data, with the same models and policy as the video.
- One shared, published demo password (`sentinel-demo`) for the `ana`, `vic` and `adm` accounts. Everything resets when the
  service restarts, so nothing a visitor does is permanent.
- The **PayPal Sandbox** data source holds one real Sandbox payment that arrived by signed webhook and was verified
  with PayPal. Visitors cannot create new PayPal payments (that needs a Sandbox buyer login).
- Without an Anthropic key, reports use the deterministic evidence version and chat is off.

## Optional switches (environment variables on the Render service)

| Variable | Effect |
|---|---|
| `ANTHROPIC_API_KEY` | Turns on the Claude narrative in reports and the chat. `SENTINEL_AI_DAILY_LIMIT` (30 by default in `render.yaml`) caps the model calls per day, so a public site cannot run up a bill. Set a spending limit on the Anthropic key as well |
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID` | Sandbox credentials only. Then point the Sandbox webhook at `https://<your-address>/paypal/webhook` and any Sandbox payment you capture appears live |

## Known limits of the free plan

- The service sleeps after about 15 minutes without a visit, so the first visit waits about a minute while it wakes up.
  Open the link yourself shortly before judging, or check it before the deadline.
- 512 MB of memory. Measured on a Python 3.11 run: about 300 MB while a replay runs, 370 MB peak. If it is ever killed for
  memory, switch the plan to Starter.
