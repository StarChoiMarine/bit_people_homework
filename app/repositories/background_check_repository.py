from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.background_check import (
    BackgroundCheckRequest,
    BackgroundCheckResult,
    BackgroundCheckWorkflowStatus,
)


OPEN_STATUSES = (
    BackgroundCheckWorkflowStatus.REQUESTED,
    BackgroundCheckWorkflowStatus.SUBMISSION_UNKNOWN,
    BackgroundCheckWorkflowStatus.PENDING,
)


def add_request(db: Session, request: BackgroundCheckRequest) -> None:
    db.add(request)


def get_request(db: Session, request_id: int) -> BackgroundCheckRequest | None:
    return db.get(BackgroundCheckRequest, request_id)


def get_open_request_for_employee(
    db: Session,
    employee_number: str,
) -> BackgroundCheckRequest | None:
    statement = select(BackgroundCheckRequest).where(
        BackgroundCheckRequest.employee_number == employee_number,
        BackgroundCheckRequest.status.in_(OPEN_STATUSES),
    )
    return db.scalar(statement)


def list_requests_for_employee(
    db: Session,
    employee_number: str,
) -> list[BackgroundCheckRequest]:
    statement = (
        select(BackgroundCheckRequest)
        .where(BackgroundCheckRequest.employee_number == employee_number)
        .order_by(BackgroundCheckRequest.requested_at.desc())
    )
    return list(db.scalars(statement))


def list_due_request_ids(
    db: Session,
    now: datetime,
    limit: int = 100,
) -> list[int]:
    statement = (
        select(BackgroundCheckRequest.id)
        .where(
            BackgroundCheckRequest.automatic_polling_stopped_at.is_(None),
            or_(
                BackgroundCheckRequest.status
                == BackgroundCheckWorkflowStatus.REQUESTED,
                and_(
                    BackgroundCheckRequest.status.in_(
                        (
                            BackgroundCheckWorkflowStatus.SUBMISSION_UNKNOWN,
                            BackgroundCheckWorkflowStatus.PENDING,
                        )
                    ),
                    BackgroundCheckRequest.next_poll_at.is_not(None),
                    BackgroundCheckRequest.next_poll_at <= now,
                ),
            ),
        )
        .order_by(BackgroundCheckRequest.requested_at)
        .limit(limit)
    )
    return list(db.scalars(statement))


def list_known_external_check_ids(db: Session) -> set[str]:
    statement = select(BackgroundCheckRequest.external_check_id).where(
        BackgroundCheckRequest.external_check_id.is_not(None)
    )
    return set(db.scalars(statement))


def add_result(db: Session, result: BackgroundCheckResult) -> None:
    db.add(result)


def get_result(db: Session, request_id: int) -> BackgroundCheckResult | None:
    return db.get(BackgroundCheckResult, request_id)


def delete_result(db: Session, result: BackgroundCheckResult) -> None:
    db.delete(result)


def list_expired_results(
    db: Session,
    now: datetime,
) -> list[BackgroundCheckResult]:
    statement = select(BackgroundCheckResult).where(
        BackgroundCheckResult.expires_at <= now
    )
    return list(db.scalars(statement))


def list_result_request_ids(
    db: Session,
    request_ids: list[int],
) -> set[int]:
    if not request_ids:
        return set()
    statement = select(BackgroundCheckResult.request_id).where(
        BackgroundCheckResult.request_id.in_(request_ids)
    )
    return set(db.scalars(statement))


def list_employee_numbers_with_available_results(db: Session) -> set[str]:
    statement = (
        select(BackgroundCheckRequest.employee_number)
        .join(
            BackgroundCheckResult,
            BackgroundCheckResult.request_id == BackgroundCheckRequest.id,
        )
        .where(
            BackgroundCheckRequest.status
            == BackgroundCheckWorkflowStatus.COMPLETED
        )
    )
    return set(db.scalars(statement))
