from sqlalchemy import text

from sentinel.db import init_db, make_engine
from sentinel.paypal_seed import seed_paypal_sample


def test_seed_adds_one_scrubbed_paypal_payment_and_is_idempotent(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    init_db(engine)
    assert seed_paypal_sample(engine) == 1
    assert seed_paypal_sample(engine) == 1  # running twice adds nothing
    with engine.connect() as c:
        payload = c.execute(text("SELECT payload FROM paypal_events")).scalar_one()
        row = c.execute(text("SELECT source, external_id FROM transactions")).one()
    assert row.source == "paypal_sandbox" and row.external_id.startswith("PP-")
    assert "@" not in payload.replace("redacted@sandbox.invalid", "")  # no real email addresses
