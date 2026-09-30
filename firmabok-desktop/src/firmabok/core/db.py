"""Database engine/session management (SQLAlchemy 2.0, SQLite).

Money amounts are stored as exact decimal *strings* (custom TypeDecorator)
so SQLite never round-trips them through floats.
"""
from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal, InvalidOperation

from sqlalchemy import String, TypeDecorator, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from . import config


class Base(DeclarativeBase):
    pass


class MoneyType(TypeDecorator):
    """Exact decimal storage as text. Never float."""
    impl = String(24)
    cache_ok = True

    def __init__(self, scale: int = 2):
        super().__init__()
        self.scale = scale
        self._quant = Decimal(1).scaleb(-scale)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        return str(value.quantize(self._quant))

    def process_result_value(self, value, dialect):
        if value is None or value == "":
            return None
        try:
            return Decimal(value)
        except InvalidOperation as exc:  # pragma: no cover
            raise ValueError(f"Korrupt belopp i databasen: {value!r}") from exc


def Money(scale: int = 2) -> MoneyType:
    return MoneyType(scale=scale)


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        config.ensure_dirs()
        _engine = create_engine(
            config.DATABASE_URL,
            echo=False,
            future=True,
            connect_args={"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {},
        )

        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False, future=True)
    return _SessionLocal


def reset_engine_for_tests(url: str) -> None:
    """Point the module at a different database (used by tests)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
    if url:
        config.DATABASE_URL = url


@contextmanager
def session_scope():
    """Context manager that commits/rolls back."""
    SessionLocal = get_session_factory()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db():
    """FastAPI dependency."""
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
