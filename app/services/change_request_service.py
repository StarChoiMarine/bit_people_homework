from datetime import UTC, date, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.audit_log import AuditAction, AuditLog
from app.models.employee import Employee, EmploymentStatus
from app.models.employee_change_request import (
    ChangeRequestStatus,
    EmployeeChangeRequest,
)
from app.repositories import (
    audit_repository,
    change_request_repository,
    employee_repository,
)
from app.services import auth_service


class ChangeRequestError(Exception):
    pass


class NoProfileChangesError(ChangeRequestError):
    pass


class PendingChangeRequestError(ChangeRequestError):
    pass


class ChangeRequestAlreadyReviewedError(ChangeRequestError):
    pass


class SelfReviewError(ChangeRequestError):
    pass


def _parse_date_of_birth(value: str) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError as error:
        raise ChangeRequestError("생년월일 값이 올바르지 않습니다.") from error


def submit_change_request(
    db: Session,
    employee: Employee,
    session_id: str,
    family_name: str,
    given_name: str,
    date_of_birth_text: str,
) -> EmployeeChangeRequest:
    family_name = family_name.strip()
    given_name = given_name.strip()
    date_of_birth_text = date_of_birth_text.strip()

    if not family_name or not given_name:
        raise ChangeRequestError("성과 이름을 모두 입력해 주세요.")
    if len(family_name) > 50 or len(given_name) > 50:
        raise ChangeRequestError("성과 이름은 각각 50자 이하여야 합니다.")

    requested_date_of_birth = _parse_date_of_birth(date_of_birth_text)
    changed_fields = []
    if family_name != employee.family_name:
        changed_fields.append("family_name")
    if given_name != employee.given_name:
        changed_fields.append("given_name")
    if requested_date_of_birth != employee.date_of_birth:
        changed_fields.append("date_of_birth")

    if not changed_fields:
        raise NoProfileChangesError("변경된 정보가 없어 요청을 생성하지 않았습니다.")
    if (
        change_request_repository.get_pending_for_employee(
            db,
            employee.employee_number,
        )
        is not None
    ):
        raise PendingChangeRequestError("이미 검토 대기 중인 요청이 있습니다.")
    if not auth_service.consume_profile_edit_grant(db, session_id):
        raise auth_service.ProfileEditAuthorizationError

    now = datetime.now(UTC).replace(tzinfo=None)
    change_request = EmployeeChangeRequest(
        employee_number=employee.employee_number,
        old_family_name=employee.family_name,
        old_given_name=employee.given_name,
        old_date_of_birth=employee.date_of_birth,
        requested_family_name=family_name,
        requested_given_name=given_name,
        requested_date_of_birth=requested_date_of_birth,
        status=ChangeRequestStatus.PENDING,
        requested_at=now,
        reviewed_at=None,
        reviewed_by=None,
    )

    try:
        change_request_repository.add(db, change_request)
        db.flush()
        audit_repository.add(
            db,
            AuditLog(
                action=AuditAction.REQUEST_PROFILE_CHANGE,
                actor_employee_number=employee.employee_number,
                target_employee_number=employee.employee_number,
                created_at=now,
                details={
                    "request_id": str(change_request.id),
                    "changed_fields": ",".join(changed_fields),
                },
            ),
        )
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise PendingChangeRequestError(
            "이미 검토 대기 중인 요청이 있습니다."
        ) from error
    except Exception:
        db.rollback()
        raise

    db.refresh(change_request)
    return change_request


def approve_change_request(
    db: Session,
    request_id: int,
    reviewer_employee_number: str,
) -> EmployeeChangeRequest | None:
    change_request = change_request_repository.get_by_id(db, request_id)
    if change_request is None:
        return None
    if change_request.employee_number == reviewer_employee_number:
        raise SelfReviewError("자신의 정보 변경 요청은 직접 승인할 수 없습니다.")
    if change_request.status != ChangeRequestStatus.PENDING:
        raise ChangeRequestAlreadyReviewedError("이미 처리된 변경 요청입니다.")

    employee = employee_repository.get_by_employee_number(
        db,
        change_request.employee_number,
    )
    if employee is None:
        return None
    if employee.employment_status != EmploymentStatus.ACTIVE:
        raise ChangeRequestError("재직 중인 직원의 요청만 승인할 수 있습니다.")

    now = datetime.now(UTC).replace(tzinfo=None)
    try:
        employee.family_name = change_request.requested_family_name
        employee.given_name = change_request.requested_given_name
        employee.full_name = (
            f"{change_request.requested_family_name}"
            f"{change_request.requested_given_name}"
        )
        employee.date_of_birth = change_request.requested_date_of_birth
        change_request.status = ChangeRequestStatus.APPROVED
        change_request.reviewed_at = now
        change_request.reviewed_by = reviewer_employee_number
        audit_repository.add(
            db,
            AuditLog(
                action=AuditAction.APPROVE_PROFILE_CHANGE,
                actor_employee_number=reviewer_employee_number,
                target_employee_number=employee.employee_number,
                created_at=now,
                details={"request_id": str(change_request.id)},
            ),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(change_request)
    return change_request


def reject_change_request(
    db: Session,
    request_id: int,
    reviewer_employee_number: str,
) -> EmployeeChangeRequest | None:
    change_request = change_request_repository.get_by_id(db, request_id)
    if change_request is None:
        return None
    if change_request.employee_number == reviewer_employee_number:
        raise SelfReviewError("자신의 정보 변경 요청은 직접 거절할 수 없습니다.")
    if change_request.status != ChangeRequestStatus.PENDING:
        raise ChangeRequestAlreadyReviewedError("이미 처리된 변경 요청입니다.")

    now = datetime.now(UTC).replace(tzinfo=None)
    try:
        change_request.status = ChangeRequestStatus.REJECTED
        change_request.reviewed_at = now
        change_request.reviewed_by = reviewer_employee_number
        change_request.employee_acknowledged_at = None
        audit_repository.add(
            db,
            AuditLog(
                action=AuditAction.REJECT_PROFILE_CHANGE,
                actor_employee_number=reviewer_employee_number,
                target_employee_number=change_request.employee_number,
                created_at=now,
                details={"request_id": str(change_request.id)},
            ),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(change_request)
    return change_request


def get_pending_employee_numbers(db: Session) -> set[str]:
    return change_request_repository.list_pending_employee_numbers(db)


def get_employee_requests(
    db: Session,
    employee_number: str,
) -> list[EmployeeChangeRequest]:
    return change_request_repository.list_for_employee(db, employee_number)


def get_pending_request(
    db: Session,
    employee_number: str,
) -> EmployeeChangeRequest | None:
    return change_request_repository.get_pending_for_employee(
        db,
        employee_number,
    )


def get_latest_unacknowledged_rejection(
    db: Session,
    employee_number: str,
) -> EmployeeChangeRequest | None:
    return change_request_repository.get_latest_unacknowledged_rejection(
        db,
        employee_number,
    )


def dismiss_rejected_change_request_notices(
    db: Session,
    employee_number: str,
) -> int:
    now = datetime.now(UTC).replace(tzinfo=None)
    try:
        acknowledged_count = change_request_repository.acknowledge_all_rejections(
            db,
            employee_number,
            now,
        )
        if acknowledged_count == 0:
            db.rollback()
            return 0

        audit_repository.add(
            db,
            AuditLog(
                action=AuditAction.DISMISS_PROFILE_CHANGE_NOTICE,
                actor_employee_number=employee_number,
                target_employee_number=employee_number,
                created_at=now,
                details={"acknowledged_count": str(acknowledged_count)},
            ),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return acknowledged_count
