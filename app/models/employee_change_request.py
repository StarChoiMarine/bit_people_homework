from datetime import date, datetime
from enum import Enum

from sqlalchemy import Date, DateTime, Enum as SqlEnum, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ChangeRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class EmployeeChangeRequest(Base):
    __tablename__ = "employee_change_requests"
    __table_args__ = (
        Index(
            "uq_pending_change_request_per_employee",
            "employee_number",
            unique=True,
            sqlite_where=text("status = 'PENDING'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_number: Mapped[str] = mapped_column(
        ForeignKey("employees.employee_number", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    old_family_name: Mapped[str] = mapped_column(String(50), nullable=False)
    old_given_name: Mapped[str] = mapped_column(String(50), nullable=False)
    old_date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    requested_family_name: Mapped[str] = mapped_column(String(50), nullable=False)
    requested_given_name: Mapped[str] = mapped_column(String(50), nullable=False)
    requested_date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[ChangeRequestStatus] = mapped_column(
        SqlEnum(
            ChangeRequestStatus,
            name="change_request_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        default=ChangeRequestStatus.PENDING,
        index=True,
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(
        ForeignKey("employees.employee_number", ondelete="RESTRICT"),
        nullable=True,
    )
    employee_acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )
