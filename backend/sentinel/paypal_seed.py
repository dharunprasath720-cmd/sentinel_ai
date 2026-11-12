"""Optional sample for a public demo: one REAL PayPal Sandbox payment (delivered by a signed webhook and
verified with PayPal when it was captured), so the PayPal Sandbox data source is not empty on a fresh deploy.
Emails are removed from the stored event. Off by default; used only by `scripts/serve.py --seed-paypal-sample`."""
import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

SEED_FILE = Path(__file__).parent / "demo_seed" / "paypal_sample.json"
_TABLES = ("accounts", "merchants", "transactions", "risk_assessments", "paypal_events")


def seed_paypal_sample(engine: Engine, path: Path = SEED_FILE) -> int:
    """Insert the sample rows (idempotent). Returns the number of transactions present afterwards."""
    data = json.loads(Path(path).read_text(encoding="utf8"))
    with engine.begin() as conn:
        for table in _TABLES:
            for row in data.get(table, []):
                cols = ", ".join(row)
                marks = ", ".join(f":{k}" for k in row)
                conn.execute(text(f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({marks})"), row)
        return conn.execute(text("SELECT count(*) FROM transactions WHERE source = 'paypal_sandbox'")).scalar_one()
