import numpy as np
import pandas as pd
import pytest

from sentinel.features.engine import FEATURE_COLUMNS, build_features
from sentinel.ingestion.synthetic import generate

T0 = pd.Timestamp("2026-03-01 12:00", tz="UTC")


def _df(rows):
    out = []
    for i, r in enumerate(rows):
        base = dict(external_id=f"T{i}", account_id="A", merchant_id="M1", device_id=None,
                    instrument_id=None, amount=10.0, currency="USD", ts=T0, type="PAYMENT",
                    payment_method=None, status="completed", geo=None, label=0,
                    source="synthetic", business_id="b")
        base.update(r)
        out.append(base)
    return pd.DataFrame(out)


def _mins(m):
    return T0 + pd.Timedelta(minutes=m)


@pytest.fixture(scope="module")
def synth():
    return generate(seed=1, n_accounts=60, days=8)


def test_columns_and_index_alignment(synth):
    f = build_features(synth)
    assert list(f.columns) == FEATURE_COLUMNS
    assert f.index.equals(synth.index)


def test_no_future_leakage(synth):
    full = build_features(synth)
    head = synth.iloc[:300]
    pd.testing.assert_frame_equal(full.iloc[:300], build_features(head))


def test_ignores_label_and_scenario(synth):
    altered = synth.copy()
    altered["label"] = 1 - altered["label"]
    altered["scenario"] = altered["scenario"].sample(frac=1, random_state=0).to_numpy()
    pd.testing.assert_frame_equal(build_features(synth), build_features(altered))


def test_single_txn_account_finite():
    f = build_features(_df([dict(account_id="ONLY")]))
    assert np.isfinite(f.to_numpy(dtype=float)).all()
    assert f.loc[0, "acct_std_amount"] == 0
    assert f.loc[0, "secs_since_prev"] == 30 * 86400  # documented "no previous txn" sentinel


def test_same_timestamp_ties_deterministic():
    df = _df([dict(amount=10 * (i + 1)) for i in range(4)] + [dict(account_id="B", ts=_mins(5))])
    f1 = build_features(df)
    shuffled = df.sample(frac=1, random_state=3)
    f2 = build_features(shuffled).loc[df.index]
    pd.testing.assert_frame_equal(f1, f2)
    tied = f1.iloc[:4]
    assert (tied["txn_count_24h"] == 0).all()  # tied rows never count each other
    assert (tied["secs_since_prev"] == 30 * 86400).all()


def test_window_counts():
    df = _df([dict(ts=_mins(0)), dict(ts=_mins(2)), dict(ts=_mins(4)),
              dict(ts=_mins(30)), dict(ts=_mins(180))])
    f = build_features(df)
    assert f.loc[2, ["txn_count_5m", "txn_count_1h", "txn_count_24h"]].tolist() == [2, 2, 2]
    assert f.loc[3, ["txn_count_5m", "txn_count_1h", "txn_count_24h"]].tolist() == [0, 3, 3]
    assert f.loc[4, ["txn_count_5m", "txn_count_1h", "txn_count_24h"]].tolist() == [0, 0, 4]
    assert f.loc[3, "secs_since_prev"] == 26 * 60


def test_device_account_count_grows_over_time():
    df = _df([
        dict(account_id="A", device_id="D", ts=_mins(0)),
        dict(account_id="B", device_id="D", ts=_mins(60)),
        dict(account_id="C", device_id="D", ts=_mins(120)),
        dict(account_id="A", device_id="D", ts=_mins(180)),
        dict(account_id="Z", device_id=None, ts=_mins(240)),
    ])
    f = build_features(df)
    assert f["device_account_count"].tolist() == [1, 2, 3, 3, 0]
