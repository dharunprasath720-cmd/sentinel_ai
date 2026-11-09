import pandas as pd


def chronological_split(
    df: pd.DataFrame, train_frac: float = 0.6, val_frac: float = 0.2
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split by time: train < validation < test. Index labels are preserved so features
    computed on the full frame (point-in-time) can be selected with `.loc`."""
    if train_frac <= 0 or val_frac <= 0 or train_frac + val_frac >= 1:
        raise ValueError("train_frac and val_frac must be positive and sum to < 1")
    ordered = df.sort_values(["ts", "external_id"], kind="mergesort")
    n = len(ordered)
    a = round(n * train_frac)
    b = a + round(n * val_frac)
    return ordered.iloc[:a], ordered.iloc[a:b], ordered.iloc[b:]
