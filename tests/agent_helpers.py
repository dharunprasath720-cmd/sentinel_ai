"""Helpers over the shared `world` fixture (see conftest.py)."""
from sqlalchemy.orm import Session

from sentinel.agent.tools import ToolBox
from sentinel.cases.orm import User
from sentinel.context import AppContext

BIZ, OTHER = "demo_biz", "other_biz"


def toolbox(world, who="ana"):
    df, scored, bundle, db = world
    session = Session(db)
    user = session.query(User).filter_by(username=who).one()
    return ToolBox(session, AppContext(business_id=BIZ, bundle=bundle), user), session


def pick(world, scenario, level_in=None):
    df, scored, *_ = world
    for i in df.index[df["scenario"] == scenario]:
        if level_in is None or scored.loc[i, "risk_level"] in level_in:
            return i
    raise AssertionError(f"no {scenario} transaction found")
