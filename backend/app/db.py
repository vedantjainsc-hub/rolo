"""SQLite engine + session helpers."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from app import config

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine(config.DB_PATH)
    return _engine


def make_engine(path: Path) -> Engine:
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 15})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    return engine


# Columns added after v1. SQLite ALTER TABLE ADD COLUMN only; nothing is ever dropped.
_MIGRATIONS: dict[str, str] = {
    "needs_name": "BOOLEAN NOT NULL DEFAULT 0",
    "source": "VARCHAR NOT NULL DEFAULT 'typed'",
    "follow_up_choices": "JSON NOT NULL DEFAULT '{}'",
    "enrichment_job": "VARCHAR",
}


def migrate(engine: Engine | None = None) -> list[str]:
    """Bring an existing contacts table up to date. Returns the columns added."""
    engine = engine or get_engine()
    added: list[str] = []
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(contacts)")}
        if not cols:
            return added  # fresh DB; create_all made it
        for name, ddl in _MIGRATIONS.items():
            if name not in cols:
                conn.exec_driver_sql(f"ALTER TABLE contacts ADD COLUMN {name} {ddl}")
                added.append(name)
    return added


def init_db() -> list[str]:
    from app import models  # noqa: F401  (registers tables)

    SQLModel.metadata.create_all(get_engine())
    return migrate()


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
