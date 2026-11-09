"""PaySim loader (simulated mobile-money data; Kaggle download, login required).

Assumptions made explicit: PaySim has no currency (USD is assumed), no device, no payment
method, and `step` is one hour from an arbitrary start (mapped to 2026-01-01 UTC).
The balance columns and `isFlaggedFraud` are dropped: they are known to leak the label.
Rows with amount 0 exist in PaySim; ingestion will reject them with a reason.
"""
from pathlib import Path

import pandas as pd

START = pd.Timestamp("2026-01-01", tz="UTC")


def load_paysim(path: Path, business_id: str = "paysim") -> pd.DataFrame:
    raw = pd.read_csv(path)
    return pd.DataFrame({
        "external_id": [f"PS{i}" for i in range(len(raw))],
        "account_id": raw["nameOrig"].astype(str),
        "merchant_id": raw["nameDest"].astype(str),
        "device_id": None,
        "instrument_id": None,
        "amount": raw["amount"].astype(float),
        "currency": "USD",
        "ts": START + pd.to_timedelta(raw["step"].astype(int), unit="h"),
        "type": raw["type"].astype(str),
        "payment_method": None,
        "status": "completed",
        "geo": None,
        "label": raw["isFraud"].astype(int),
        "source": "paysim",
        "business_id": business_id,
    })
