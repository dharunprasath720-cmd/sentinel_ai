from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.pool import StaticPool

from sentinel.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None) -> Engine:
    url = url or get_settings().database_url
    if url.startswith("sqlite") and ":memory:" in url:
        return create_engine(url, poolclass=StaticPool,
                             connect_args={"check_same_thread": False})
    return create_engine(url)


def init_db(engine: Engine) -> None:
    from sentinel.cases import orm as _cases  # noqa: F401  (registers tables)
    from sentinel.paypal import orm as _paypal  # noqa: F401  (registers tables)
    from sentinel.ingestion import orm  # noqa: F401  (registers tables)
    Base.metadata.create_all(engine)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
