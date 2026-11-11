"""Read-only endpoints behind the dashboard. Registered inside create_app so they share its
authentication; every route is business-scoped and readable by all roles."""
from fastapi import Depends, FastAPI, HTTPException, Path, Query
from sqlalchemy.orm import Session

from sentinel.agent.tools import ToolBox, ToolUnavailable
from sentinel.cases.orm import User
from sentinel.context import AppContext
from sentinel.dashboard import queries
from sentinel.dashboard.queries import Level, Source
from sentinel.security import NotFound


def register_dashboard(app: FastAPI, get_session, current_user, context: AppContext | None) -> None:
    @app.get("/metrics/overview")
    def metrics_overview(source: Source = "synthetic", session: Session = Depends(get_session),
                         user: User = Depends(current_user)):
        return queries.overview(session, user.business_id, source)

    @app.get("/metrics/models")
    def metrics_models(user: User = Depends(current_user)):
        bundle = getattr(context, "bundle", None)
        if bundle is None:
            raise HTTPException(status_code=503, detail="no model is loaded")
        return queries.models_summary(bundle)

    @app.get("/transactions")
    def transactions(source: Source = "synthetic", level: Level | None = None,
                     limit: int = Query(50, ge=1, le=200), session: Session = Depends(get_session),
                     user: User = Depends(current_user)):
        return queries.recent_transactions(session, user.business_id, source, level, limit)

    @app.get("/transactions/{transaction_id}")
    def transaction_detail(transaction_id: str = Path(min_length=1, max_length=200),
                           session: Session = Depends(get_session), user: User = Depends(current_user)):
        tools = ToolBox(session, context, user)
        details = tools.get_transaction_details(transaction_id)  # NotFound -> 404 (also other businesses)
        try:
            risk = tools.get_transaction_risk(transaction_id)
        except NotFound:
            risk = None
        explanation, unavailable = None, None
        try:
            explanation = tools.get_model_explanation(transaction_id)
        except ToolUnavailable as exc:
            unavailable = str(exc)
        try:
            related = tools.get_related_accounts(details["transaction"]["account_id"])
        except NotFound:
            related = None
        return {"details": details, "risk": risk, "explanation": explanation,
                "explanation_unavailable": unavailable, "related": related}

    @app.get("/cases")
    def cases(session: Session = Depends(get_session), user: User = Depends(current_user)):
        return queries.list_cases(session, user.business_id)

    @app.get("/graph/clusters")
    def graph_clusters(source: Source = "synthetic", session: Session = Depends(get_session),
                       user: User = Depends(current_user)):
        return queries.flagged_clusters(session, user.business_id, source, ToolBox(session, context, user))

    @app.get("/graph")
    def graph(cluster: str | None = Query(None, min_length=1, max_length=200),
              account: str | None = Query(None, min_length=1, max_length=200),
              hours: int = Query(24, ge=1, le=168), source: Source = "synthetic",
              session: Session = Depends(get_session), user: User = Depends(current_user)):
        if (cluster is None) == (account is None):
            raise HTTPException(status_code=422, detail="give exactly one of cluster or account")
        if cluster is not None:
            return queries.graph_for_cluster(session, user.business_id, ToolBox(session, context, user), cluster)
        return queries.graph_for_account(session, user.business_id, source, account, hours)
