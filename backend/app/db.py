"""Motor SQLAlchemy, sesión, Base declarativa y tipo FechaHoraUTC (ADR-0006)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeDecorator

from app.config import get_settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class FechaHoraUTC(TypeDecorator):
    """DateTime con zona: exige datetimes con zona, guarda en UTC y devuelve con tzinfo=UTC."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Se requiere un datetime con zona horaria.")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def ahora_utc() -> datetime:
    return datetime.now(UTC)


def crear_engine(url: str) -> Engine:
    """Crea un engine; en SQLite activa claves foráneas y, en memoria, usa StaticPool."""
    kwargs: dict[str, Any] = {}
    es_sqlite = url.startswith("sqlite")
    if es_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
        if url in ("sqlite://", "sqlite+pysqlite://") or ":memory:" in url:
            kwargs["poolclass"] = StaticPool
    else:
        kwargs["pool_pre_ping"] = True
    engine = create_engine(url, **kwargs)
    if es_sqlite:

        @event.listens_for(engine, "connect")
        def _pragma(dbapi_conn: Any, _registro: Any) -> None:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


engine = crear_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=True, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
