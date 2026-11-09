import pandas as pd
import pytest

from sentinel.ingestion.synthetic import generate
from sentinel.models.split import chronological_split


@pytest.fixture(scope="module")
def df():
    return generate(seed=3, n_accounts=80, days=10)


def test_ordering_and_disjointness(df):
    tr, va, te = chronological_split(df)
    assert tr["ts"].max() <= va["ts"].min()
    assert va["ts"].max() <= te["ts"].min()
    ids = [set(x["external_id"]) for x in (tr, va, te)]
    assert not (ids[0] & ids[1]) and not (ids[1] & ids[2]) and not (ids[0] & ids[2])
    assert len(tr) + len(va) + len(te) == len(df)


def test_sizes_match_fractions(df):
    tr, va, te = chronological_split(df, train_frac=0.6, val_frac=0.2)
    n = len(df)
    assert abs(len(tr) - 0.6 * n) <= 1
    assert abs(len(va) - 0.2 * n) <= 1


def test_rejects_bad_fractions(df):
    with pytest.raises(ValueError):
        chronological_split(df, train_frac=0.8, val_frac=0.2)
