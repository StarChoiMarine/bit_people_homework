from datetime import datetime
from enum import Enum

from sqlalchemy import JSON, DateTime, Enum as SqlEnum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditAction(str, Enum):
    CREATE_EMPLOYEE = "CREATE_EMPLOYEE"
    TERMINATE_EMPLOYEE = "TERMINATE_EMPLOYEE"
    REQUEST_PROFILE_CHANGE = "REQUEST_PROFILE_CHANGE"
    APPROVE_PROFILE_CHANGE = "APPROVE_PROFILE_CHANGE"
    REJECT_PROFILE_CHANGE = "REJECT_PROFILE_CHANGE"
    DISMISS_PROFILE_CHANGE_NOTICE = "DISMISS_PROFILE_CHANGE_NOTICE"
    CHANGE_PASSWORD = "CHANGE_PASSWORD"


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[AuditAction] = mapped_column(
        SqlEnum(
            AuditAction,
            name="audit_action",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    actor_employee_number: Mapped[str] = mapped_column(
        ForeignKey("employees.employee_number", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    target_employee_number: Mapped[str] = mapped_column(
        ForeignKey("employees.employee_number", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        index=True,
    )
    details: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
