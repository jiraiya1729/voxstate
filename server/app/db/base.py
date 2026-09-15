"""SQLAlchemy declarative base used by ORM models and Alembic migrations."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class that registers SQLAlchemy ORM models for migrations and queries."""

    pass
