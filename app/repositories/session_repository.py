from datetime import datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.login_session import LoginSession


def get_by_hash(db: Session, session_id_hash: str) -> LoginSession | None:
    return db.get(LoginSession, session_id_hash)


def add(db: Session, login_session: LoginSession) -> None:
    db.add(login_session)


def delete(db: Session, login_session: LoginSession) -> None:
    db.delete(login_session)


def revoke_active_for_employee(
    db: Session,
    employee_number: str,
    revoked_at: datetime,
) -> int:
    statement = (
        update(LoginSession)
        .where(
            LoginSession.employee_number == employee_number,
            LoginSession.revoked_at.is_(None),
            LoginSession.expires_at > revoked_at,
        )
        .values(revoked_at=revoked_at)
    )
    result = db.execute(statement)
    return result.rowcount or 0


def revoke_other_active_for_employee(
    db: Session,
    employee_number: str,
    excluded_session_id_hash: str,
    revoked_at: datetime,
) -> int:
    statement = (
        update(LoginSession)
        .where(
            LoginSession.employee_number == employee_number,
            LoginSession.session_id_hash != excluded_session_id_hash,
            LoginSession.revoked_at.is_(None),
            LoginSession.expires_at > revoked_at,
        )
        .values(revoked_at=revoked_at)
    )
    result = db.execute(statement)
    return result.rowcount or 0
