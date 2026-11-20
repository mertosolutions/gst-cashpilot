from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()
_is_sqlite = settings.database_url.startswith("sqlite")
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def dialect_name() -> str:
    return engine.dialect.name


def set_tenant(db: Session, business_id: str) -> None:
    """On PostgreSQL / AlloyDB this activates row level security for the transaction.
    SQLite has no RLS, so there the services filter by business_id themselves."""
    if dialect_name() == "postgresql":
        db.execute(text("SELECT set_config('app.business_id', :bid, true)"), {"bid": business_id})


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
