import numpy as np
import pandas as pd
import pytest

from sentinel.ingestion.schema import TransactionIn
from sentinel.ingestion.synthetic import generate


@pytest.fixture(scope="module")
def df():
    return generate(seed=42)


def test_deterministic_for_seed():
    a = generate(seed=7, n_accounts=120, days=10)
    b = generate(seed=7, n_accounts=120, days=10)
    c = generate(seed=8, n_accounts=120, days=10)
    pd.testing.assert_frame_equal(a, b)
    assert not a.equals(c)


def test_rows_satisfy_ingestion_schema(df):
    sample = df.sample(300, random_state=0).drop(columns=["scenario"])
    sample = sample.astype(object).where(sample.notna(), None)
    for rec in sample.to_dict("records"):
        TransactionIn(**rec)
    assert (df["source"] == "synthetic").all()


def test_planted_ring(df):
    ring = df[df["scenario"] == "ring"]
    assert (ring["label"] == 1).all()
    found = False
    for _, g in ring.groupby("device_id"):
        if g["account_id"].nunique() >= 4:
            assert g["merchant_id"].nunique() == 1
            assert (g["ts"].max() - g["ts"].min()) <= pd.Timedelta(hours=2)
            found = True
    assert found


def test_legit_unusual_not_fraud(df):
    lu = df[df["scenario"] == "legit_unusual"]
    assert len(lu) >= 5
    assert (lu["label"] == 0).all()
    normal = df[df["scenario"] == "normal"]
    for _, row in lu.iterrows():
        acct = normal[normal["account_id"] == row["account_id"]]["amount"]
        assert row["amount"] > np.percentile(acct, 99)


def test_fraud_rate_realistic(df):
    assert 0.005 <= df["label"].mean() <= 0.05


def test_not_every_unusual_is_fraud(df):
    assert set(df[df["scenario"] == "burst"]["label"]) == {0, 1}


def test_shared_device_not_always_fraud(df):
    per_dev = df.dropna(subset=["device_id"]).groupby("device_id").agg(
        n_acct=("account_id", "nunique"), fraud=("label", "max"))
    assert ((per_dev["n_acct"] >= 2) & (per_dev["fraud"] == 0)).any()
