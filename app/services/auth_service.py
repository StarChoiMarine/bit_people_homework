import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.passwords import verify_password
from app.models.employee import Employee, EmploymentStatus
from app.models.login_session import LoginSession
from app.repositories import employee_repository, session_repository


SESSION_COOKIE_NAME = "session_id"
SESSION_LIFETIME = timedelta(hours=8)
TERMINATED_ACCOUNT_MESSAGE = "퇴사 처리된 계정입니다. 관리자에게 문의하세요."


class TerminatedAccountError(Exception):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _hash_session_id(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def authenticate(
    db: Session,
    login_id: str,
    password: str,
) -> Employee | None:
    normalized_login_id = login_id.strip().lower()
    if not normalized_login_id or len(password) > 1024:
        return None

    employee = employee_repository.get_by_login_id(db, normalized_login_id)
    if employee is None:
        return None
    if not verify_password(password, employee.password_hash):
        return None
    if employee.employment_status == EmploymentStatus.TERMINATED:
        raise TerminatedAccountError
    return employee


def create_session(db: Session, employee: Employee) -> str:
    session_id = secrets.token_urlsafe(32)
    now = _utc_now()
    login_session = LoginSession(
        session_id_hash=_hash_session_id(session_id),
        employee_number=employee.employee_number,
        created_at=now,
        expires_at=now + SESSION_LIFETIME,
        revoked_at=None,
    )
    session_repository.add(db, login_session)
    db.commit()
    return session_id


def get_employee_for_session(
    db: Session,
    session_id: str,
) -> Employee | None:
    login_session = session_repository.get_by_hash(
        db,
        _hash_session_id(session_id),
    )
    if login_session is None:
        return None

    if login_session.expires_at <= _utc_now():
        session_repository.delete(db, login_session)
        db.commit()
        return None

    employee = employee_repository.get_by_employee_number(
        db,
        login_session.employee_number,
    )
    if employee is None:
        session_repository.delete(db, login_session)
        db.commit()
        return None
    if employee.employment_status == EmploymentStatus.TERMINATED:
        raise TerminatedAccountError
    if login_session.revoked_at is not None:
        return None
    return employee


def revoke_all_active_sessions(db: Session, employee_number: str) -> int:
    """Revoke sessions without committing the caller's transaction."""
    return session_repository.revoke_active_for_employee(
        db,
        employee_number,
        revoked_at=_utc_now(),
    )


def delete_session(db: Session, session_id: str) -> None:
    login_session = session_repository.get_by_hash(
        db,
        _hash_session_id(session_id),
    )
    if login_session is None:
        return
    session_repository.delete(db, login_session)
    db.commit()
