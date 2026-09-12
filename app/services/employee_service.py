from datetime import UTC, date, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.passwords import hash_password
from app.models.audit_log import AuditAction, AuditLog
from app.models.employee import Employee, EmployeeRole, EmploymentStatus
from app.repositories import audit_repository, employee_repository
from app.services import auth_service


class EmployeeCreationError(Exception):
    pass


class EmployeeUpdateError(Exception):
    pass


class SelfAdminEditError(Exception):
    pass


class SelfTerminationError(Exception):
    pass


def list_employees(db: Session) -> list[Employee]:
    return employee_repository.list_all(db)


def get_employee_detail(db: Session, employee_number: str) -> Employee | None:
    return employee_repository.get_by_employee_number(db, employee_number)


def terminate_employee(
    db: Session,
    employee_number: str,
    actor_employee_number: str,
) -> Employee | None:
    employee = employee_repository.get_by_employee_number(db, employee_number)
    if employee is None:
        return None
    if employee.employee_number == actor_employee_number:
        raise SelfTerminationError("자기 자신은 퇴사 처리할 수 없습니다.")
    if employee.employment_status == EmploymentStatus.TERMINATED:
        return employee

    try:
        now = datetime.now(UTC).replace(tzinfo=None)
        employee.employment_status = EmploymentStatus.TERMINATED
        employee.terminated_at = now
        auth_service.revoke_all_active_sessions(db, employee_number)
        audit_repository.add(
            db,
            AuditLog(
                action=AuditAction.TERMINATE_EMPLOYEE,
                actor_employee_number=actor_employee_number,
                target_employee_number=employee_number,
                created_at=now,
                details={
                    "previous_status": EmploymentStatus.ACTIVE.value,
                    "new_status": EmploymentStatus.TERMINATED.value,
                },
            ),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(employee)
    return employee


def create_employee(
    db: Session,
    employee_number: str,
    login_id: str,
    family_name: str,
    given_name: str,
    date_of_birth_text: str,
    role_text: str,
    password: str,
    actor_employee_number: str,
) -> Employee:
    employee_number = employee_number.strip().upper()
    login_id = login_id.strip().lower()
    family_name = family_name.strip()
    given_name = given_name.strip()
    full_name = f"{family_name}{given_name}"
    date_of_birth_text = date_of_birth_text.strip()
    role_text = role_text.strip().upper()

    if not all((employee_number, login_id, family_name, given_name)):
        raise EmployeeCreationError("필수 항목을 모두 입력해 주세요.")
    if employee_repository.get_by_employee_number(db, employee_number) is not None:
        raise EmployeeCreationError("이미 사용 중인 사번입니다.")
    if employee_repository.get_by_login_id(db, login_id) is not None:
        raise EmployeeCreationError("이미 사용 중인 로그인 아이디입니다.")
    if (
        len(password) < 8
        or len(password) > 1024
        or all(character.isalnum() for character in password)
    ):
        raise EmployeeCreationError(
            "비밀번호는 8자 이상이며 특수문자를 포함해야 합니다."
        )

    try:
        parsed_date_of_birth = (
            date.fromisoformat(date_of_birth_text) if date_of_birth_text else None
        )
        role = EmployeeRole(role_text)
    except ValueError as error:
        raise EmployeeCreationError("생년월일 또는 역할 값이 올바르지 않습니다.") from error

    employee = Employee(
        employee_number=employee_number,
        login_id=login_id,
        full_name=full_name,
        family_name=family_name,
        given_name=given_name,
        date_of_birth=parsed_date_of_birth,
        role=role,
        employment_status=EmploymentStatus.ACTIVE,
        terminated_at=None,
        password_hash=hash_password(password),
    )

    try:
        employee_repository.add(db, employee)
        db.flush()
        audit_repository.add(
            db,
            AuditLog(
                action=AuditAction.CREATE_EMPLOYEE,
                actor_employee_number=actor_employee_number,
                target_employee_number=employee.employee_number,
                created_at=datetime.now(UTC).replace(tzinfo=None),
                details={
                    "login_id": employee.login_id,
                    "full_name": employee.full_name,
                    "role": employee.role.value,
                },
            ),
        )
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise EmployeeCreationError(
            "사번 또는 로그인 아이디가 이미 존재합니다."
        ) from error
    except Exception:
        db.rollback()
        raise

    db.refresh(employee)
    return employee


def update_employee_by_admin(
    db: Session,
    employee_number: str,
    actor_employee_number: str,
    session_id: str,
    login_id: str,
    family_name: str,
    given_name: str,
    date_of_birth_text: str,
    role_text: str,
    new_password: str = "",
) -> Employee | None:
    employee = employee_repository.get_by_employee_number(db, employee_number)
    if employee is None:
        return None
    if employee.employee_number == actor_employee_number:
        raise SelfAdminEditError(
            "관리자 자신의 정보는 정보 변경 요청을 통해 다른 관리자의 승인을 받아야 합니다."
        )

    login_id = login_id.strip().lower()
    family_name = family_name.strip()
    given_name = given_name.strip()
    full_name = f"{family_name}{given_name}"
    date_of_birth_text = date_of_birth_text.strip()
    role_text = role_text.strip().upper()

    if not all((login_id, family_name, given_name)):
        raise EmployeeUpdateError("로그인 아이디, 성, 이름을 모두 입력해 주세요.")
    if len(login_id) > 50 or len(family_name) > 50 or len(given_name) > 50:
        raise EmployeeUpdateError("입력값이 허용 길이를 초과했습니다.")

    existing_login = employee_repository.get_by_login_id(db, login_id)
    if existing_login is not None and existing_login.employee_number != employee_number:
        raise EmployeeUpdateError("이미 사용 중인 로그인 아이디입니다.")

    try:
        parsed_date_of_birth = (
            date.fromisoformat(date_of_birth_text) if date_of_birth_text else None
        )
        role = EmployeeRole(role_text)
    except ValueError as error:
        raise EmployeeUpdateError("생년월일 또는 역할 값이 올바르지 않습니다.") from error

    if new_password and (
        len(new_password) < 8
        or len(new_password) > 1024
        or all(character.isalnum() for character in new_password)
    ):
        raise EmployeeUpdateError(
            "새 비밀번호는 8자 이상이며 특수문자를 포함해야 합니다."
        )

    changed_fields = []
    if employee.login_id != login_id:
        changed_fields.append("login_id")
    if employee.family_name != family_name:
        changed_fields.append("family_name")
    if employee.given_name != given_name:
        changed_fields.append("given_name")
    if employee.date_of_birth != parsed_date_of_birth:
        changed_fields.append("date_of_birth")
    if employee.role != role:
        changed_fields.append("role")
    if new_password:
        changed_fields.append("password")

    if not changed_fields:
        raise EmployeeUpdateError("변경된 정보가 없습니다.")
    if not auth_service.consume_profile_edit_grant(db, session_id):
        raise auth_service.ProfileEditAuthorizationError

    security_fields = {"login_id", "role", "password"}
    try:
        employee.login_id = login_id
        employee.family_name = family_name
        employee.given_name = given_name
        employee.full_name = full_name
        employee.date_of_birth = parsed_date_of_birth
        employee.role = role
        if new_password:
            employee.password_hash = hash_password(new_password)

        revoked_session_count = 0
        if security_fields.intersection(changed_fields):
            revoked_session_count = auth_service.revoke_all_active_sessions(
                db,
                employee.employee_number,
            )

        audit_repository.add(
            db,
            AuditLog(
                action=AuditAction.UPDATE_EMPLOYEE,
                actor_employee_number=actor_employee_number,
                target_employee_number=employee.employee_number,
                created_at=datetime.now(UTC).replace(tzinfo=None),
                details={
                    "changed_fields": ",".join(changed_fields),
                    "sessions_revoked": str(revoked_session_count),
                },
            ),
        )
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise EmployeeUpdateError(
            "이미 사용 중인 로그인 아이디입니다."
        ) from error
    except Exception:
        db.rollback()
        raise

    db.refresh(employee)
    return employee
