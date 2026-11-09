import numpy as np
import pandas as pd
import pytest

from sentinel.behaviour.engine import BehaviourEngine
from sentinel.ingestion.synthetic import generate

T0 = pd.Timestamp("2026-03-01 12:00", tz="UTC")


def tx(i, amount=10.0, minutes=0, merchant="M1", status="completed", account="A"):
    return dict(external_id=f"T{i}", account_id=account, merchant_id=merchant, amount=amount,
                ts=T0 + pd.Timedelta(minutes=minutes), status=status)


def seeded(n=20, varied=True):
    """Engine with n daily payments at 12:00 to M1, amounts 10/11/12 (or all 10)."""
    eng = BehaviourEngine()
    for d in range(n):
        eng.update(tx(d, amount=10.0 + (d % 3 if varied else 0), minutes=d * 1440))
    return eng


def day(n):
    return n * 1440


def test_first_transaction_is_neutral():
    ind = BehaviourEngine().indicators(tx(0))
    assert ind.n_history == 0 and ind.deviation_score == 0 and ind.reasons == []
    assert ind.amount_robust_z == 0 and not ind.new_merchant and not ind.off_hours


def test_mad_zero_no_nan():
    eng = seeded(varied=False)  # 20 identical amounts: MAD = 0
    ind = eng.indicators(tx(99, amount=50.0, minutes=day(21)))
    assert np.isfinite(ind.amount_robust_z) and ind.amount_robust_z > 3.5
    assert 0 <= ind.deviation_score <= 1


def test_sudden_spend_increase_flags():
    ind = seeded().indicators(tx(99, amount=200.0, minutes=day(21)))
    assert ind.amount_robust_z > 3.5
    assert any(r.startswith("Amount") for r in ind.reasons)
    assert ind.deviation_score >= 0.5


def test_burst_detected():
    eng = seeded()
    last = None
    for k in range(6):
        t = tx(100 + k, minutes=day(21) + k)
        last = eng.indicators(t)
        eng.update(t)
    assert last.burst_count_10m == 5
    assert any("last 10 minutes" in r for r in last.reasons)


def test_new_merchant_and_off_hours():
    ind = seeded().indicators(tx(99, minutes=day(21) - 9 * 60, merchant="NEW"))  # 03:00
    assert ind.new_merchant and ind.off_hours
    assert any("merchant" in r.lower() for r in ind.reasons)
    assert any("hours" in r.lower() for r in ind.reasons)


def test_failed_streak():
    eng = seeded()
    for k in range(3):
        eng.update(tx(200 + k, minutes=day(21) + k, status="failed"))
    ind = eng.indicators(tx(300, minutes=day(21) + 5, status="failed"))
    assert ind.failed_streak == 4
    assert any("failed" in r for r in ind.reasons)


def test_contaminated_rows_do_not_move_baseline():
    eng = seeded()
    before = eng.profile("A")
    for k in range(10):
        eng.update(tx(500 + k, amount=5000.0, minutes=day(21) + k), contaminated=True)
    after = eng.profile("A")
    assert after["median_amount"] == before["median_amount"]
    assert after["n_history"] == before["n_history"]


def test_deviation_is_not_a_verdict():
    ind = seeded().indicators(tx(99, amount=110.0, minutes=day(21)))  # 10x typical, legit-looking
    assert ind.reasons  # explained
    assert ind.deviation_score < 1.0  # a single deviation never reaches the maximum


def test_replay_is_point_in_time():
    df = generate(seed=1, n_accounts=60, days=8)
    full = BehaviourEngine().replay(df)
    head = BehaviourEngine().replay(df.iloc[:200])
    pd.testing.assert_frame_equal(full.iloc[:200], head)


def test_replay_ties_never_count_each_other():
    rows = [tx(i, minutes=day(i)) for i in range(6)] + [tx(10, minutes=day(7)), tx(11, minutes=day(7))]
    df = pd.DataFrame(rows)
    out = BehaviourEngine().replay(df)
    assert out["n_history"].tolist()[-2:] == [6, 6]
