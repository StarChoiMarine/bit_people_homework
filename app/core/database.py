import os
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker


DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "data/employee_portal.db"))
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"


class Base(DeclarativeBase):
    pass


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@event.listens_for(engine, "connect")
def configure_sqlite_connection(
    dbapi_connection: sqlite3.Connection,
    connection_record: object,
) -> None:
    """Enable the SQLite options required by this application."""
    del connection_record

    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()

