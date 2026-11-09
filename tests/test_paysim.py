"""Uses tests/fixtures/paysim_sample.csv: a tiny hand-written fixture in PaySim's column
layout (NOT real PaySim data). The real file goes in data/raw/paysim.csv."""
from pathlib import Path

import pandas as pd

from sentinel.ingestion.paysim import load_paysim
from sentinel.ingestion.schema import TransactionIn

FIXTURE = Path(__file__).parent / "fixtures" / "paysim_sample.csv"
LEAKY = {"oldbalanceOrg", "newbalanceOrig", "oldbalanceDest", "newbalanceDest", "isFlaggedFraud"}


def test_columns_match_schema_and_balances_dropped():
    df = load_paysim(FIXTURE)
    assert set(TransactionIn.model_fields) <= set(df.columns)
    assert not (LEAKY & set(df.columns))
    assert "isFraud" not in df.columns


def test_timestamps_aware_and_monotonic_in_step():
    df = load_paysim(FIXTURE)
    assert str(df["ts"].dt.tz) == "UTC"
    raw = pd.read_csv(FIXTURE)
    assert (df["ts"].diff().dropna() >= pd.Timedelta(0)).all()
    assert df["ts"].iloc[0] == pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(hours=int(raw["step"].iloc[0]))


def test_source_labels_and_ids():
    df = load_paysim(FIXTURE)
    assert (df["source"] == "paysim").all()
    assert df["external_id"].is_unique
    assert df["label"].sum() == 4
    assert df["merchant_id"].notna().all() and df["device_id"].isna().all()
