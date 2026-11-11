"""Read-only endpoints behind the dashboard. Registered inside create_app so they share its
authentication; every route is business-scoped and readable by all roles."""
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from sentinel.cases.orm import User
from sentinel.context import AppContext
from sentinel.dashboard import queries
from sentinel.dashboard.queries import Source


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
