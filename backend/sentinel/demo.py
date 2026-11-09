"""Reproducible demo world: synthetic history in the database, a model trained on that history only,
a live scorer warmed on it, and a held-back stream to replay.

  history (first 70% by time) -> DB, scored in batch, assessments + alerts stored, model trained on it
  stream  (last 30%)          -> AppContext.demo_frame, labels REMOVED (unknown at scoring time);
                                 ground truth kept separately in stream_truth.pkl for evaluation only
Demo users get random passwords written to a git-ignored env file (never printed, never stored in
plaintext anywhere else); the database only holds argon2 hashes.
"""
import json
import secrets
from pathlib import Path

import joblib
import pandas as pd
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from sentinel.cases import services
from sentinel.cases.orm import RiskAssessmentRow, User
from sentinel.context import AppContext
from sentinel.db import init_db, make_engine, session_scope
from sentinel.ingestion.orm import Transaction
from sentinel.ingestion.service import ingest
from sentinel.ingestion.synthetic import generate
from sentinel.live.scorer import LiveScorer
from sentinel.models.split import chronological_split
from sentinel.models.train import TrainedBundle, train
from sentinel.pipeline import fit_normalisers, score_frame
from sentinel.risk.engine import DEFAULT_POLICY_PATH, RiskAssessment, RiskEngine, load_policy
from sentinel.security import hash_password

BUSINESS = "demo_biz"
USERS = (("ana", "analyst"), ("vic", "viewer"), ("adm", "admin"))
INPUT_KEYS = ("ml_prob", "anomaly", "behaviour", "graph", "velocity", "account_history", "merchant_risk")


def _records(df: pd.DataFrame) -> list[dict]:
    clean = df.drop(columns=[c for c in ("scenario",) if c in df.columns])
    return clean.astype(object).where(clean.notna(), None).to_dict("records")


def store_batch_scores(session: Session, business: str, frame: pd.DataFrame, scored: pd.DataFrame,
                       model_version: str) -> None:
    """Persist batch `score_frame` output as assessments (with details) and create HIGH+ alerts."""
    for i, r in scored.iterrows():
        a = RiskAssessment(risk_score=r.risk_score, risk_level=r.risk_level,
                           recommended_action=r.recommended_action,
                           calibrated_fraud_probability=r.calibrated_fraud_probability,
                           risk_factors=list(r.risk_factors), contributions={}, policy_version=r.policy_version)
        cluster = None if pd.isna(r.cluster_id) else str(r.cluster_id)
        services.record_assessment(
            session, business, frame.loc[i, "external_id"], a, model_version,
            details={"inputs": {k: float(r[k]) for k in INPUT_KEYS}, "behaviour_reasons": [],
                     "cluster_id": cluster, "late": False})
    services.create_alerts(session, business, session.query(RiskAssessmentRow).all())


def transactions_frame(session: Session, business: str) -> pd.DataFrame:
    rows = (session.query(Transaction).filter_by(business_id=business)
            .order_by(Transaction.ts, Transaction.external_id).all())
    return pd.DataFrame([{
        "external_id": r.external_id, "account_id": r.account_id, "merchant_id": r.merchant_id,
        "device_id": r.device_id, "instrument_id": r.instrument_id, "amount": r.amount,
        "ts": pd.to_datetime(r.ts, utc=True), "type": r.type, "status": r.status,
        "business_id": r.business_id} for r in rows])


def build_demo(db_url: str, out_dir: Path, env_file: Path, seed: int = 42, n_accounts: int = 500,
               days: int = 30, business: str = BUSINESS, log=print) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log("generating synthetic data")
    df = generate(seed=seed, n_accounts=n_accounts, days=days)
    df["business_id"] = business
    cut = int(len(df) * 0.7)
    history, stream = df.iloc[:cut], df.iloc[cut:]
    log(f"training on {len(history)} history rows")
    bundle = train(history, seed=seed, dataset="demo")
    norms = fit_normalisers(chronological_split(history)[0])
    log("scoring history in batch")
    scored = score_frame(history, bundle, RiskEngine(load_policy(DEFAULT_POLICY_PATH)), norms)

    db = make_engine(db_url)
    init_db(db)
    passwords = {name: secrets.token_urlsafe(12) for name, _ in USERS}
    with session_scope(db) as s:
        for name, role in USERS:
            s.add(User(username=name, password_hash=hash_password(passwords[name]), role=role,
                       business_id=business))
        ingest(s, _records(history))
        store_batch_scores(s, business, history, scored, bundle.version)

    bundle.save(out_dir)
    joblib.dump(norms, out_dir / "normalisers.joblib")
    stream.drop(columns=["scenario"]).assign(label=None).to_pickle(out_dir / "stream.pkl")
    stream[["external_id", "label", "scenario"]].set_index("external_id").to_pickle(out_dir / "stream_truth.pkl")
    (out_dir / "meta.json").write_text(json.dumps({
        "version": bundle.version, "business": business, "seed": seed, "n_accounts": n_accounts,
        "days": days, "history_rows": len(history), "stream_rows": len(stream)}, indent=2))
    # credentials: written to a git-ignored file, never printed
    env_file = Path(env_file)
    env_file.write_text("\n".join([f"SENTINEL_JWT_SECRET={secrets.token_urlsafe(32)}"]
                                  + [f"{n.upper()}_PASSWORD={p}" for n, p in passwords.items()]) + "\n")
    log(f"demo built: {len(history)} history rows, {len(stream)} stream rows; credentials in {env_file.name}")


def load_demo(db_url: str, out_dir: Path, business: str = BUSINESS) -> tuple[Engine, AppContext]:
    out_dir = Path(out_dir)
    bundle = TrainedBundle.load(out_dir)
    norms = joblib.load(out_dir / "normalisers.joblib")
    risk_engine = RiskEngine(load_policy(DEFAULT_POLICY_PATH))
    db = make_engine(db_url)
    with Session(db) as s:
        history = transactions_frame(s, business)
        levels = {a.txn_external_id: a.risk_level for a in s.query(RiskAssessmentRow).filter_by(business_id=business)}
    history_levels = history["external_id"].map(levels)
    scorer = LiveScorer(bundle, risk_engine, norms, history, history_levels=history_levels)
    ctx = AppContext(business_id=business, bundle=bundle, risk_engine=risk_engine, normalisers=norms,
                     live_scorer=scorer, demo_frame=pd.read_pickle(out_dir / "stream.pkl"),
                     model_version=bundle.version)
    return db, ctx


def load_truth(out_dir: Path) -> pd.DataFrame:
    """Ground truth (label, scenario) of the replay stream, indexed by external_id. Evaluation only."""
    return pd.read_pickle(Path(out_dir) / "stream_truth.pkl")
