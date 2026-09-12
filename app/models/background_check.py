from datetime import date, datetime
from enum import Enum

from sqlalchemy import (
    Date,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BackgroundCheckWorkflowStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SUBMISSION_UNKNOWN = "SUBMISSION_UNKNOWN"
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class BackgroundCheckResultValue(str, Enum):
    CLEAR = "CLEAR"
    FLAGGED = "FLAGGED"


class ResultDeletionReason(str, Enum):
    ACKNOWLEDGED = "ACKNOWLEDGED"
    TTL_EXPIRED = "TTL_EXPIRED"


class BackgroundCheckRequest(Base):
    __tablename__ = "background_check_requests"
    __table_args__ = (
        Index(
            "uq_open_background_check_per_employee",
            "employee_number",
            unique=True,
            sqlite_where=text(
                "status IN ('REQUESTED', 'SUBMISSION_UNKNOWN', 'PENDING') "
                "OR (status = 'COMPLETED' AND result_deleted_at IS NULL)"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_number: Mapped[str] = mapped_column(
        ForeignKey("employees.employee_number", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    requested_by_employee_number: Mapped[str] = mapped_column(
        ForeignKey("employees.employee_number", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    request_reason: Mapped[str] = mapped_column(String(500), nullable=False)
    submitted_full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    submitted_family_name: Mapped[str] = mapped_column(String(50), nullable=False)
    submitted_given_name: Mapped[str] = mapped_column(String(50), nullable=False)
    submitted_date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    external_check_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        unique=True,
    )
    status: Mapped[BackgroundCheckWorkflowStatus] = mapped_column(
        SqlEnum(
            BackgroundCheckWorkflowStatus,
            name="background_check_workflow_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        default=BackgroundCheckWorkflowStatus.REQUESTED,
        index=True,
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    submission_started_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )
    tracking_started_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_poll_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        index=True,
    )
    get_attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    automatic_polling_stopped_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )
    last_error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    result_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )
    result_deletion_reason: Mapped[ResultDeletionReason | None] = mapped_column(
        SqlEnum(
            ResultDeletionReason,
            name="background_check_result_deletion_reason",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=True,
    )


class BackgroundCheckResult(Base):
    __tablename__ = "background_check_results"

    request_id: Mapped[int] = mapped_column(
        ForeignKey("background_check_requests.id", ondelete="CASCADE"),
        primary_key=True,
    )
    result: Mapped[BackgroundCheckResultValue] = mapped_column(
        SqlEnum(
            BackgroundCheckResultValue,
            name="background_check_result_value",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        index=True,
    )
