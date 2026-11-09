"""PayPal Sandbox traffic and synthetic traffic must never share scorer state, even inside one business."""
import pandas as pd
import pytest

from sentinel.ingestion.synthetic import generate
from sentinel.live.scorer import LiveScorer
from sentinel.models.split import chronological_split
from sentinel.models.train import train
from sentinel.pipeline import fit_normalisers
from sentinel.risk.engine import DEFAULT_POLICY_PATH, RiskEngine, load_policy


@pytest.fixture(scope="module")
def small():
    df = generate(seed=3, n_accounts=150, days=20)
    bundle = train(df, seed=42)
    return df, bundle, RiskEngine(load_policy(DEFAULT_POLICY_PATH)), fit_normalisers(chronological_split(df)[0])


def paypal_event(i, account, ts, business):
    return {"external_id": f"PP-CAP-{i}", "account_id": account, "merchant_id": "MERCH1", "device_id": None,
            "instrument_id": None, "amount": 20.0, "currency": "USD", "ts": ts, "type": "PAYMENT",
            "payment_method": "paypal", "status": "completed", "geo": None, "label": None,
            "source": "paypal_sandbox", "business_id": business}


def test_a_paypal_event_dated_now_does_not_switch_off_behaviour_scoring_for_synthetic_traffic(small):
    df, bundle, engine, norms = small
    cut = int(len(df) * 0.8)
    hist = df.iloc[:cut]
    biz = hist["business_id"].iloc[0]
    acct = hist.groupby("account_id").size().idxmax()
    typical = hist[hist["account_id"] == acct]["amount"].median()
    outlier = dict(df.iloc[cut].to_dict(), external_id="OUT-1", account_id=acct, amount=typical * 60,
                   ts=hist["ts"].max() + pd.Timedelta(minutes=1))

    alone = LiveScorer(bundle, engine, norms, hist).score(dict(outlier))
    assert alone.inputs["behaviour"] > 0 and not alone.late  # the outlier is visible when nothing else happened

    shared = LiveScorer(bundle, engine, norms, hist)
    shared.score(paypal_event(1, "PAYPAL_UNLINKED:CAP-1", pd.Timestamp("2026-11-09T10:00:00Z"), biz))
    after = shared.score(dict(outlier))
    assert after.late is False  # a November PayPal event must not make January traffic "late"
    assert after.inputs["behaviour"] == pytest.approx(alone.inputs["behaviour"])


def test_unlinked_paypal_payers_do_not_inherit_each_others_velocity(small):
    df, bundle, engine, norms = small
    hist = df.iloc[: int(len(df) * 0.8)]
    biz = hist["business_id"].iloc[0]
    scorer = LiveScorer(bundle, engine, norms, hist)
    base = pd.Timestamp("2026-11-09T10:00:00Z")
    out = [scorer.score(paypal_event(i, f"PAYPAL_UNLINKED:CAP-{i}", base + pd.Timedelta(seconds=2 * i), biz))
           for i in range(12)]
    assert all(o.features["txn_count_1h"] == 0 and o.inputs["velocity"] == 0 for o in out)
    assert all(o.business_id == biz for o in out)  # the partition is internal; outputs keep the real business


def test_synthetic_and_paypal_events_with_the_same_account_id_stay_separate(small):
    df, bundle, engine, norms = small
    hist = df.iloc[: int(len(df) * 0.8)]
    biz = hist["business_id"].iloc[0]
    acct = hist["account_id"].iloc[0]
    scorer = LiveScorer(bundle, engine, norms, hist)
    base = pd.Timestamp("2026-11-09T10:00:00Z")
    first = scorer.score(paypal_event(1, acct, base, biz))
    assert first.features["txn_count_24h"] == 0 and first.features["acct_mean_amount"] == 0  # no synthetic history leaks in
