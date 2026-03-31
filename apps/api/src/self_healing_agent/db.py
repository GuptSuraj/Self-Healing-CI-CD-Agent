from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from self_healing_agent.config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, future=True, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_metadata():
    from self_healing_agent.repositories.jobs import RepairJobRecord
    from self_healing_agent.repositories.sql import ArtifactRecord, AuditEventRecord, RepairRunRecord

    _ = (RepairRunRecord, AuditEventRecord, RepairJobRecord, ArtifactRecord)
    return Base.metadata


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
