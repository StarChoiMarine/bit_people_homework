from datetime import date, datetime
from enum import Enum

from sqlalchemy import Date, DateTime, Enum as SqlEnum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EmployeeRole(str, Enum):
    EMPLOYEE = "EMPLOYEE"
    ADMIN = "ADMIN"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class Employee(Base):
    __tablename__ = "employees"

    employee_number: Mapped[str] = mapped_column(String(20), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    family_name: Mapped[str] = mapped_column(String(50), nullable=False)
    given_name: Mapped[str] = mapped_column(String(50), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    role: Mapped[EmployeeRole] = mapped_column(
        SqlEnum(
            EmployeeRole,
            name="employee_role",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        default=EmployeeRole.EMPLOYEE,
    )
    employment_status: Mapped[EmploymentStatus] = mapped_column(
        SqlEnum(
            EmploymentStatus,
            name="employment_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        default=EmploymentStatus.ACTIVE,
    )
    terminated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

