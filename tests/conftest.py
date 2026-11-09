"""Shared, expensive test world (built once per session): synthetic data, a trained model, batch
scores, and a database seeded with transactions, assessments, alerts and users."""
import pytest

from sentinel.cases.orm import User
from sentinel.db import init_db, make_engine, session_scope
from sentinel.demo import store_batch_scores
from sentinel.ingestion.service import ingest
from sentinel.ingestion.synthetic import generate
from sentinel.models.split import chronological_split
from sentinel.models.train import train
from sentinel.pipeline import fit_normalisers, score_frame
from sentinel.risk.engine import DEFAULT_POLICY_PATH, RiskEngine, load_policy
from sentinel.security import hash_password

BIZ, OTHER, PW = "demo_biz", "other_biz", "Passw0rd-for-agent-tests"


@pytest.fixture(scope="session")
def world():
    df = generate(seed=42, n_accounts=150, days=20)
    tr, _, _ = chronological_split(df)
    bundle = train(df, seed=42)
    scored = score_frame(df, bundle, RiskEngine(load_policy(DEFAULT_POLICY_PATH)), fit_normalisers(tr))
    db = make_engine("sqlite:///:memory:")
    init_db(db)
    clean = df.drop(columns=["scenario"])
    records = clean.astype(object).where(clean.notna(), None).to_dict("records")
    pw = hash_password(PW)
    with session_scope(db) as s:
        s.add_all([User(username="ana", password_hash=pw, role="analyst", business_id=BIZ),
                   User(username="vic", password_hash=pw, role="viewer", business_id=BIZ),
                   User(username="bob", password_hash=pw, role="analyst", business_id=OTHER)])
        ingest(s, records)
        store_batch_scores(s, BIZ, df, scored, "m-test")
    return df, scored, bundle, db
