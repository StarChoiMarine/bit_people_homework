import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.passwords import hash_password, verify_password
from app.models.audit_log import AuditAction, AuditLog
from app.models.employee import Employee, EmploymentStatus
from app.models.login_session import LoginSession
from app.models.profile_edit_grant import ProfileEditGrant
from app.repositories import (
    audit_repository,
    employee_repository,
    profile_edit_repository,
    session_repository,
)


SESSION_COOKIE_NAME = "session_id"
SESSION_LIFETIME = timedelta(hours=8)
PROFILE_EDIT_GRANT_LIFETIME = timedelta(minutes=5)
TERMINATED_ACCOUNT_MESSAGE = "퇴사 처리된 계정입니다. 관리자에게 문의하세요."


class TerminatedAccountError(Exception):
    pass


class ProfileEditAuthorizationError(Exception):
    pass


class PasswordChangeError(Exception):
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


def verify_password_for_profile_edit(
    db: Session,
    session_id: str,
    employee: Employee,
    password: str,
) -> bool:
    if len(password) > 1024 or not verify_password(password, employee.password_hash):
        return False

    session_id_hash = _hash_session_id(session_id)
    if session_repository.get_by_hash(db, session_id_hash) is None:
        return False

    expires_at = _utc_now() + PROFILE_EDIT_GRANT_LIFETIME
    grant = profile_edit_repository.get_by_session_hash(db, session_id_hash)
    if grant is None:
        profile_edit_repository.add(
            db,
            ProfileEditGrant(
                session_id_hash=session_id_hash,
                expires_at=expires_at,
            ),
        )
    else:
        grant.expires_at = expires_at
    db.commit()
    return True


def has_profile_edit_grant(db: Session, session_id: str) -> bool:
    grant = profile_edit_repository.get_by_session_hash(
        db,
        _hash_session_id(session_id),
    )
    if grant is None:
        return False
    if grant.expires_at <= _utc_now():
        profile_edit_repository.delete(db, grant)
        db.commit()
        return False
    return True


def consume_profile_edit_grant(db: Session, session_id: str) -> bool:
    grant = profile_edit_repository.get_by_session_hash(
        db,
        _hash_session_id(session_id),
    )
    if grant is None or grant.expires_at <= _utc_now():
        return False
    profile_edit_repository.delete(db, grant)
    return True


def change_password(
    db: Session,
    employee: Employee,
    current_session_id: str,
    current_password: str,
    new_password: str,
    new_password_confirmation: str,
) -> int:
    if len(current_password) > 1024 or not verify_password(
        current_password,
        employee.password_hash,
    ):
        raise PasswordChangeError("현재 비밀번호가 올바르지 않습니다.")
    if new_password != new_password_confirmation:
        raise PasswordChangeError("새 비밀번호가 서로 일치하지 않습니다.")
    if (
        len(new_password) < 8
        or len(new_password) > 1024
        or all(character.isalnum() for character in new_password)
    ):
        raise PasswordChangeError(
            "새 비밀번호는 8자 이상이며 특수문자를 포함해야 합니다."
        )
    if verify_password(new_password, employee.password_hash):
        raise PasswordChangeError("기존 비밀번호와 다른 비밀번호를 입력해 주세요.")

    now = _utc_now()
    current_session_id_hash = _hash_session_id(current_session_id)
    try:
        employee.password_hash = hash_password(new_password)
        revoked_session_count = session_repository.revoke_other_active_for_employee(
            db,
            employee.employee_number,
            excluded_session_id_hash=current_session_id_hash,
            revoked_at=now,
        )
        profile_edit_grant = profile_edit_repository.get_by_session_hash(
            db,
            current_session_id_hash,
        )
        if profile_edit_grant is not None:
            profile_edit_repository.delete(db, profile_edit_grant)
        audit_repository.add(
            db,
            AuditLog(
                action=AuditAction.CHANGE_PASSWORD,
                actor_employee_number=employee.employee_number,
                target_employee_number=employee.employee_number,
                created_at=now,
                details={
                    "other_sessions_revoked": str(revoked_session_count),
                },
            ),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return revoked_session_count


def delete_session(db: Session, session_id: str) -> None:
    login_session = session_repository.get_by_hash(
        db,
        _hash_session_id(session_id),
    )
    if login_session is None:
        return
    session_repository.delete(db, login_session)
    db.commit()
