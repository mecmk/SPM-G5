"""SQLAlchemy engine / session plumbing.

The schema itself is owned by the SQL migrations in backend/db/migrations; the ORM models in
each feature package (app/auth/models.py, app/venues/models.py, ...) mirror the tables the
application code touches. tests/test_schema.py::test_orm_models_match_database fails if a
model and the real table disagree, so keep them in step.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, create_engine, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class UUIDPrimaryKeyMixin:
    """`id UUID PRIMARY KEY DEFAULT gen_random_uuid()` - shared by most tables."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


class TimestampMixin:
    """`created_at` / `updated_at` maintained by the database (default + trigger)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


def get_db():
    """FastAPI dependency yielding one SQLAlchemy session per request.

    Overridden in tests (tests/conftest.py) with a session bound to a rolled-back transaction.
    """
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
