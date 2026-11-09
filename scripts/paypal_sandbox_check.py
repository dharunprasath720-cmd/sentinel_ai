"""Live PayPal Sandbox check (needs YOUR Sandbox app credentials and a Sandbox BUYER account).

  python scripts/paypal_sandbox_check.py [--account ACC_00007] [--amount 25.00]

It creates an order, prints the approval URL, waits while YOU approve it in a browser with a
Sandbox buyer account, captures it, and prints the SHAPE of the responses (keys and value types,
never values), so we can confirm the response paths this code assumes. With scripts/serve.py running
behind a tunnel and the webhook registered, the capture then arrives as a PAYMENT.CAPTURE.COMPLETED
webhook and shows up in the live stream.

Never run against production credentials. Reads PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET from the
environment or .env; nothing secret is printed.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sentinel.paypal.client import PayPalClient, PayPalError  # noqa: E402


def shape(obj, depth=0):
    """Keys and types only: no amounts, emails or ids."""
    if isinstance(obj, dict):
        return {k: shape(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        return [shape(obj[0], depth + 1)] if obj else []
    return type(obj).__name__


def main() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default=None,
                    help="optional custom_id stored on the order; it becomes the fraud account id. Leave unset "
                         "to test an unlinked payer (its own pseudo-account); do NOT reuse a synthetic account id")
    ap.add_argument("--amount", default="25.00")
    args = ap.parse_args()
    cid, secret = os.environ.get("PAYPAL_CLIENT_ID"), os.environ.get("PAYPAL_CLIENT_SECRET")
    if not (cid and secret):
        sys.exit("Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET (Sandbox app) in the environment or .env")

    client = PayPalClient(cid, secret)
    try:
        order = client.create_order(args.amount, "USD", custom_id=args.account)
        print("order created:", order["id"], "status", order["status"])
        print("\nOpen this URL, log in with a SANDBOX BUYER account and approve the payment:\n ", order["approve_url"])
        input("\nPress Enter once you have approved it... ")
        cap = client.capture_order(order["id"])
        print("\ncapture ok -> status:", cap["status"], "| amount:", cap["amount"], cap["currency"],
              "| capture id:", cap["capture_id"])
        print("\nresponse shape (confirms the paths the code assumes):")
        print("  capture response:", shape(cap["raw"]))
        print("  order after capture:", shape(client.get_order(order["id"])))
    except PayPalError as exc:
        print(f"\nPayPal error: status={exc.status} name={exc.name} issue={exc.issue} debug_id={exc.debug_id}")
        sys.exit(1)


if __name__ == "__main__":
    main()
