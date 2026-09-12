from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.audit_log import AuditAction, AuditLog
from app.models.background_check import (
    BackgroundCheckRequest,
    BackgroundCheckResultValue,
    BackgroundCheckWorkflowStatus,
    ResultDeletionReason,
)
from app.models.employee import Employee, EmploymentStatus
from app.repositories import (
    audit_repository,
    background_check_repository,
    employee_repository,
)


MAX_REASON_LENGTH = 500


class BackgroundCheckError(Exception):
    pass


class BackgroundCheckNotFoundError(BackgroundCheckError):
    pass


class BackgroundCheckNotAllowedError(BackgroundCheckError):
    pass


class BackgroundCheckAlreadyOpenError(BackgroundCheckError):
    pass


class BackgroundCheckResultUnavailableError(BackgroundCheckError):
    pass


@dataclass(frozen=True)
class BackgroundCheckResultView:
    request_id: int
    employee_number: str
    result: BackgroundCheckResultValue
    expires_at: datetime


@dataclass(frozen=True)
class BackgroundCheckStatusView:
    status: BackgroundCheckWorkflowStatus
    is_final: bool
    result_available: bool


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _validate_reason(reason: str, label: str) -> str:
    normalized = reason.strip()
    if not normalized:
        raise BackgroundCheckError(f"{label}를 입력해 주세요.")
    if len(normalized) > MAX_REASON_LENGTH:
        raise BackgroundCheckError(
            f"{label}는 {MAX_REASON_LENGTH}자 이하여야 합니다."
        )
    return normalized


def create_request(
    db: Session,
    employee_number: str,
    requested_by_employee_number: str,
    request_reason: str,
    now: datetime | None = None,
) -> BackgroundCheckRequest:
    employee = employee_repository.get_by_employee_number(db, employee_number)
    if employee is None:
        raise BackgroundCheckNotFoundError("직원을 찾을 수 없습니다.")
    if employee.employment_status != EmploymentStatus.ACTIVE:
        raise BackgroundCheckNotAllowedError(
            "재직 중인 직원만 Background Check를 요청할 수 있습니다."
        )
    if employee.date_of_birth is None:
        raise BackgroundCheckNotAllowedError(
            "생년월일이 확인되지 않아 Background Check를 요청할 수 없습니다."
        )
    normalized_reason = _validate_reason(request_reason, "요청 사유")
    if (
        background_check_repository.get_open_request_for_employee(
            db,
            employee_number,
        )
        is not None
    ):
        raise BackgroundCheckAlreadyOpenError(
            "이미 진행 중인 Background Check 요청이 있습니다."
        )

    created_at = now or _utc_now()
    background_request = BackgroundCheckRequest(
        employee_number=employee_number,
        requested_by_employee_number=requested_by_employee_number,
        request_reason=normalized_reason,
        external_check_id=None,
        status=BackgroundCheckWorkflowStatus.REQUESTED,
        requested_at=created_at,
        submission_started_at=None,
        tracking_started_at=None,
        completed_at=None,
        next_poll_at=None,
        get_attempt_count=0,
        automatic_polling_stopped_at=None,
        last_error_code=None,
        result_deleted_at=None,
        result_deletion_reason=None,
    )

    try:
        background_check_repository.add_request(db, background_request)
        db.flush()
        audit_repository.add(
            db,
            AuditLog(
                action=AuditAction.REQUEST_BACKGROUND_CHECK,
                actor_employee_number=requested_by_employee_number,
                target_employee_number=employee_number,
                created_at=created_at,
                details={"request_id": str(background_request.id)},
            ),
        )
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise BackgroundCheckAlreadyOpenError(
            "이미 진행 중인 Background Check 요청이 있습니다."
        ) from error
    except Exception:
        db.rollback()
        raise

    db.refresh(background_request)
    return background_request


def purge_expired_results(
    db: Session,
    now: datetime | None = None,
) -> int:
    deleted_at = now or _utc_now()
    expired_results = background_check_repository.list_expired_results(
        db,
        deleted_at,
    )
    if not expired_results:
        return 0

    try:
        for result in expired_results:
            background_request = background_check_repository.get_request(
                db,
                result.request_id,
            )
            if background_request is not None:
                background_request.result_deleted_at = deleted_at
                background_request.result_deletion_reason = (
                    ResultDeletionReason.TTL_EXPIRED
                )
            background_check_repository.delete_result(db, result)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return len(expired_results)


def list_employee_requests(
    db: Session,
    employee_number: str,
    now: datetime | None = None,
) -> tuple[list[BackgroundCheckRequest], set[int]]:
    purge_expired_results(db, now)
    requests = background_check_repository.list_requests_for_employee(
        db,
        employee_number,
    )
    result_request_ids = background_check_repository.list_result_request_ids(
        db,
        [request.id for request in requests],
    )
    return requests, result_request_ids


def get_employee_numbers_requiring_attention(
    db: Session,
    now: datetime | None = None,
) -> set[str]:
    purge_expired_results(db, now)
    return background_check_repository.list_employee_numbers_with_available_results(
        db
    )


def get_request(
    db: Session,
    request_id: int,
) -> BackgroundCheckRequest | None:
    return background_check_repository.get_request(db, request_id)


def get_status(
    db: Session,
    request_id: int,
    now: datetime | None = None,
) -> BackgroundCheckStatusView:
    purge_expired_results(db, now)
    background_request = background_check_repository.get_request(db, request_id)
    if background_request is None:
        raise BackgroundCheckNotFoundError("Background Check 요청을 찾을 수 없습니다.")
    result_available = (
        background_check_repository.get_result(db, request_id) is not None
    )
    is_final = background_request.status in {
        BackgroundCheckWorkflowStatus.COMPLETED,
        BackgroundCheckWorkflowStatus.FAILED,
    } or background_request.automatic_polling_stopped_at is not None
    return BackgroundCheckStatusView(
        status=background_request.status,
        is_final=is_final,
        result_available=result_available,
    )


def resume_safe_lookup(
    db: Session,
    request_id: int,
    now: datetime | None = None,
) -> BackgroundCheckRequest:
    resumed_at = now or _utc_now()
    background_request = background_check_repository.get_request(db, request_id)
    if background_request is None:
        raise BackgroundCheckNotFoundError("Background Check 요청을 찾을 수 없습니다.")
    if background_request.status not in {
        BackgroundCheckWorkflowStatus.SUBMISSION_UNKNOWN,
        BackgroundCheckWorkflowStatus.PENDING,
    }:
        raise BackgroundCheckNotAllowedError("재확인할 수 있는 요청 상태가 아닙니다.")
    if background_request.automatic_polling_stopped_at is None:
        raise BackgroundCheckNotAllowedError("현재 자동 조회가 진행 중입니다.")

    background_request.tracking_started_at = resumed_at
    background_request.get_attempt_count = 0
    background_request.next_poll_at = resumed_at
    background_request.automatic_polling_stopped_at = None
    background_request.last_error_code = None
    db.commit()
    return background_request


def view_result(
    db: Session,
    request_id: int,
    admin: Employee,
    access_reason: str,
    now: datetime | None = None,
) -> BackgroundCheckResultView:
    viewed_at = now or _utc_now()
    background_request = background_check_repository.get_request(db, request_id)
    if background_request is None:
        raise BackgroundCheckNotFoundError("Background Check 요청을 찾을 수 없습니다.")
    normalized_reason = _validate_reason(access_reason, "열람 사유")

    result = background_check_repository.get_result(db, request_id)
    if result is None:
        raise BackgroundCheckResultUnavailableError(
            "결과가 아직 준비되지 않았거나 이미 삭제되었습니다."
        )
    if result.expires_at <= viewed_at:
        purge_expired_results(db, viewed_at)
        raise BackgroundCheckResultUnavailableError("결과의 24시간 보관 기한이 만료되었습니다.")

    result_value = result.result
    result_expires_at = result.expires_at

    try:
        background_check_repository.delete_result(db, result)
        background_request.result_deleted_at = viewed_at
        background_request.result_deletion_reason = ResultDeletionReason.ACKNOWLEDGED
        audit_repository.add(
            db,
            AuditLog(
                action=AuditAction.VIEW_BACKGROUND_CHECK_RESULT,
                actor_employee_number=admin.employee_number,
                target_employee_number=background_request.employee_number,
                created_at=viewed_at,
                details={
                    "request_id": str(background_request.id),
                    "access_reason": normalized_reason,
                },
            ),
        )
        audit_repository.add(
            db,
            AuditLog(
                action=AuditAction.ACKNOWLEDGE_BACKGROUND_CHECK_RESULT,
                actor_employee_number=admin.employee_number,
                target_employee_number=background_request.employee_number,
                created_at=viewed_at,
                details={"request_id": str(background_request.id)},
            ),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return BackgroundCheckResultView(
        request_id=background_request.id,
        employee_number=background_request.employee_number,
        result=result_value,
        expires_at=result_expires_at,
    )


def acknowledge_result(
    db: Session,
    request_id: int,
    admin: Employee,
    now: datetime | None = None,
) -> BackgroundCheckRequest:
    acknowledged_at = now or _utc_now()
    background_request = background_check_repository.get_request(db, request_id)
    if background_request is None:
        raise BackgroundCheckNotFoundError("Background Check 요청을 찾을 수 없습니다.")
    result = background_check_repository.get_result(db, request_id)
    if result is None:
        raise BackgroundCheckResultUnavailableError(
            "결과가 이미 확인되었거나 만료되어 삭제되었습니다."
        )
    if result.expires_at <= acknowledged_at:
        purge_expired_results(db, acknowledged_at)
        raise BackgroundCheckResultUnavailableError("결과의 24시간 보관 기한이 만료되었습니다.")

    try:
        background_check_repository.delete_result(db, result)
        background_request.result_deleted_at = acknowledged_at
        background_request.result_deletion_reason = ResultDeletionReason.ACKNOWLEDGED
        audit_repository.add(
            db,
            AuditLog(
                action=AuditAction.ACKNOWLEDGE_BACKGROUND_CHECK_RESULT,
                actor_employee_number=admin.employee_number,
                target_employee_number=background_request.employee_number,
                created_at=acknowledged_at,
                details={"request_id": str(background_request.id)},
            ),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return background_request
