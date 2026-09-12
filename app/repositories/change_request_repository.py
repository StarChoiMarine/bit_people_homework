from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.employee_change_request import (
    ChangeRequestStatus,
    EmployeeChangeRequest,
)


def add(db: Session, change_request: EmployeeChangeRequest) -> None:
    db.add(change_request)


def get_by_id(db: Session, request_id: int) -> EmployeeChangeRequest | None:
    return db.get(EmployeeChangeRequest, request_id)


def get_pending_for_employee(
    db: Session,
    employee_number: str,
) -> EmployeeChangeRequest | None:
    statement = select(EmployeeChangeRequest).where(
        EmployeeChangeRequest.employee_number == employee_number,
        EmployeeChangeRequest.status == ChangeRequestStatus.PENDING,
    )
    return db.scalar(statement)


def list_for_employee(
    db: Session,
    employee_number: str,
) -> list[EmployeeChangeRequest]:
    statement = (
        select(EmployeeChangeRequest)
        .where(EmployeeChangeRequest.employee_number == employee_number)
        .order_by(EmployeeChangeRequest.requested_at.desc())
    )
    return list(db.scalars(statement))


def list_pending_employee_numbers(db: Session) -> set[str]:
    statement = select(EmployeeChangeRequest.employee_number).where(
        EmployeeChangeRequest.status == ChangeRequestStatus.PENDING
    )
    return set(db.scalars(statement))


def get_latest_unacknowledged_rejection(
    db: Session,
    employee_number: str,
) -> EmployeeChangeRequest | None:
    statement = (
        select(EmployeeChangeRequest)
        .where(
            EmployeeChangeRequest.employee_number == employee_number,
            EmployeeChangeRequest.status == ChangeRequestStatus.REJECTED,
            EmployeeChangeRequest.employee_acknowledged_at.is_(None),
        )
        .order_by(
            EmployeeChangeRequest.reviewed_at.desc(),
            EmployeeChangeRequest.id.desc(),
        )
        .limit(1)
    )
    return db.scalar(statement)


def acknowledge_all_rejections(
    db: Session,
    employee_number: str,
    acknowledged_at: datetime,
) -> int:
    statement = (
        update(EmployeeChangeRequest)
        .where(
            EmployeeChangeRequest.employee_number == employee_number,
            EmployeeChangeRequest.status == ChangeRequestStatus.REJECTED,
            EmployeeChangeRequest.employee_acknowledged_at.is_(None),
        )
        .values(employee_acknowledged_at=acknowledged_at)
    )
    result = db.execute(statement)
    return result.rowcount
