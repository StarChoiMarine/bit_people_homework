from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.employee import Employee


def get_by_employee_number(
    db: Session,
    employee_number: str,
) -> Employee | None:
    return db.get(Employee, employee_number)


def get_by_login_id(db: Session, login_id: str) -> Employee | None:
    statement = select(Employee).where(Employee.login_id == login_id)
    return db.scalar(statement)


def list_all(db: Session) -> list[Employee]:
    statement = select(Employee).order_by(Employee.employee_number)
    return list(db.scalars(statement))


def add(db: Session, employee: Employee) -> None:
    db.add(employee)
