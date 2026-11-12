"""Run the SENTINEL API on the demo world.

  python scripts/serve.py              # build the demo on first run (a few minutes), then serve
  python scripts/serve.py --rebuild    # discard the demo database and rebuild everything

Credentials: generated demo logins and the JWT secret live in .env.demo (git-ignored, never printed).
Optional integrations are read from the environment or .env (git-ignored):
  ANTHROPIC_API_KEY                                   -> investigation agent narrative + chat
  PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET, PAYPAL_WEBHOOK_ID -> PayPal Sandbox webhook route
Webhooks need a public URL: point a tunnel (ngrok / cloudflared) at http://127.0.0.1:<port>/paypal/webhook.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import uvicorn  # noqa: E402

from sentinel.agent.llm import AnthropicLLM  # noqa: E402
from sentinel.api.app import create_app  # noqa: E402
from sentinel.api.frontend import mount_frontend  # noqa: E402
from sentinel.demo import build_demo, load_demo  # noqa: E402
from sentinel.db import make_engine  # noqa: E402
from sentinel.paypal.client import PayPalClient  # noqa: E402
from sentinel.paypal_seed import seed_paypal_sample  # noqa: E402
from sentinel.paypal.settings import PayPalSettings  # noqa: E402


def load_env_file(path: Path) -> None:
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    ap.add_argument("--host", default=os.environ.get("SENTINEL_HOST", "127.0.0.1"),
                    help="use 0.0.0.0 to accept outside connections (a hosted demo); default is this machine only")
    ap.add_argument("--build-only", action="store_true", help="build the demo data and exit (used when baking a container image)")
    ap.add_argument("--seed-paypal-sample", action="store_true",
                    help="add one real, verified PayPal Sandbox payment to the demo database (public demo only)")
    ap.add_argument("--accounts", type=int, default=500)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--home", type=Path, default=ROOT,
                    help="where demo.db, artifacts/demo and .env.demo live (default: the project folder)")
    args = ap.parse_args()

    home = args.home
    art, db_file, env_demo = home / "artifacts" / "demo", home / "demo.db", home / ".env.demo"
    db_url = f"sqlite:///{db_file.as_posix()}"
    if args.rebuild or not (art / "meta.json").exists():
        db_file.unlink(missing_ok=True)
        build_demo(db_url, art, env_file=env_demo, n_accounts=args.accounts, days=args.days)
    if args.seed_paypal_sample:
        print("PayPal sample payments in the database:", seed_paypal_sample(make_engine(db_url)))
    if args.build_only:
        print("demo built; exiting (--build-only)")
        return
    load_env_file(env_demo)
    load_env_file(ROOT / ".env")

    print("loading the demo world (warming the live scorer)...")
    engine, ctx = load_demo(db_url, art)
    try:
        s = PayPalSettings.from_env()
        ctx.paypal, ctx.webhook_id = PayPalClient(s.client_id, s.client_secret), s.webhook_id
        print("PayPal Sandbox: configured")
    except RuntimeError as exc:
        print(f"PayPal Sandbox: not configured ({exc})")
    ctx.llm = AnthropicLLM.from_env()
    print("Claude agent:", "configured" if ctx.llm else "not configured (reports are deterministic, chat is off)")
    print(f"Demo logins are in {env_demo.name} (usernames ana / vic / adm). API docs: http://127.0.0.1:{args.port}/docs")
    app = create_app(engine, context=ctx)
    if mount_frontend(app, ROOT / "frontend" / "dist"):
        print(f"Dashboard: http://127.0.0.1:{args.port}/")
    else:
        print("Dashboard: not built (run `npm run build --prefix frontend`); the API still works")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
