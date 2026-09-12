from datetime import date

from sqlalchemy.orm import Session

from app.core.passwords import hash_password
from app.models.employee import Employee, EmployeeRole, EmploymentStatus
from app.repositories.employee_repository import get_by_employee_number


SEED_ACCOUNTS = [
    {
        "employee_number": "ADM-001",
        "login_id": "admin",
        "full_name": "시스템관리자",
        "family_name": "시스템",
        "given_name": "관리자",
        "date_of_birth": None,
        "role": EmployeeRole.ADMIN,
        "password": "admin123",
    },
    {
        "employee_number": "EMP-001",
        "login_id": "emp001",
        "full_name": "김민준",
        "family_name": "김",
        "given_name": "민준",
        "date_of_birth": "1990-03-15",
        "role": EmployeeRole.EMPLOYEE,
        "password": "rlaalswns@@",
    },
    {
        "employee_number": "EMP-002",
        "login_id": "emp002",
        "full_name": "김민준",
        "family_name": "김",
        "given_name": "민준",
        "date_of_birth": "1994-11-02",
        "role": EmployeeRole.EMPLOYEE,
        "password": "rlaalswns@@",
    },
    {
        "employee_number": "EMP-003",
        "login_id": "emp003",
        "full_name": "남궁서준",
        "family_name": "남궁",
        "given_name": "서준",
        "date_of_birth": "1988-07-21",
        "role": EmployeeRole.EMPLOYEE,
        "password": "skarndtjwns@@",
    },
    {
        "employee_number": "EMP-004",
        "login_id": "emp004",
        "full_name": "황보라온",
        "family_name": "황보",
        "given_name": "라온",
        "date_of_birth": "1995-02-09",
        "role": EmployeeRole.EMPLOYEE,
        "password": "ghkdqhfkdhs@@",
    },
    {
        "employee_number": "EMP-005",
        "login_id": "emp005",
        "full_name": "김솔",
        "family_name": "김",
        "given_name": "솔",
        "date_of_birth": "1992-12-30",
        "role": EmployeeRole.EMPLOYEE,
        "password": "rlathf@@",
    },
    {
        "employee_number": "EMP-006",
        "login_id": "emp006",
        "full_name": "선우진",
        "family_name": "선",
        "given_name": "우진",
        "date_of_birth": "1991-05-05",
        "role": EmployeeRole.EMPLOYEE,
        "password": "tjsdnwls@@",
    },
    {
        "employee_number": "EMP-007",
        "login_id": "emp007",
        "full_name": "이서연",
        "family_name": "이",
        "given_name": "서연",
        "date_of_birth": None,
        "role": EmployeeRole.EMPLOYEE,
        "password": "dltjdus@@",
    },
    {
        "employee_number": "EMP-008",
        "login_id": "emp008",
        "full_name": "박민준",
        "family_name": "박",
        "given_name": "민준",
        "date_of_birth": "1993-08-17",
        "role": EmployeeRole.EMPLOYEE,
        "password": "qkralswns@@",
    },
    {
        "employee_number": "EMP-009",
        "login_id": "emp009",
        "full_name": "최지우",
        "family_name": "최",
        "given_name": "지우",
        "date_of_birth": "1996-04-03",
        "role": EmployeeRole.EMPLOYEE,
        "password": "chlwldn@@",
    },
    {
        "employee_number": "EMP-010",
        "login_id": "emp010",
        "full_name": "정하윤",
        "family_name": "정",
        "given_name": "하윤",
        "date_of_birth": "1989-10-11",
        "role": EmployeeRole.EMPLOYEE,
        "password": "wjdgkdbs@@",
    },
]


def seed_accounts(db: Session) -> None:
    for account in SEED_ACCOUNTS:
        employee_number = account["employee_number"]
        if get_by_employee_number(db, employee_number) is not None:
            continue

        date_of_birth = account["date_of_birth"]
        employee = Employee(
            employee_number=employee_number,
            login_id=account["login_id"],
            full_name=account["full_name"],
            family_name=account["family_name"],
            given_name=account["given_name"],
            date_of_birth=(
                date.fromisoformat(date_of_birth) if date_of_birth else None
            ),
            role=account["role"],
            employment_status=EmploymentStatus.ACTIVE,
            terminated_at=None,
            password_hash=hash_password(account["password"]),
        )
        db.add(employee)

    db.commit()
