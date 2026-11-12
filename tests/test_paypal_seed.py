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


def test_set_demo_passwords_makes_every_demo_user_log_in_with_the_shared_password(tmp_path):
    from sentinel.cases.orm import User
    from sentinel.db import session_scope
    from sentinel.demo import set_demo_passwords
    from sentinel.security import hash_password, verify_password

    engine = make_engine(f"sqlite:///{(tmp_path / 'u.db').as_posix()}")
    init_db(engine)
    with session_scope(engine) as s:
        for name, role in [("ana", "analyst"), ("vic", "viewer"), ("adm", "admin")]:
            s.add(User(username=name, password_hash=hash_password("random-" + name), role=role, business_id="b"))
    assert set_demo_passwords(engine, "shared-pw") == 3
    with session_scope(engine) as s:
        assert all(verify_password("shared-pw", u.password_hash) for u in s.query(User).all())
        assert not verify_password("random-ana", s.query(User).filter_by(username="ana").one().password_hash)
