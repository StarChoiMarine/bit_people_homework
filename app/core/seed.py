import json
import os
from datetime import date
from pathlib import Path

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
    },
    {
        "employee_number": "EMP-001",
        "login_id": "emp001",
        "full_name": "김민준",
        "family_name": "김",
        "given_name": "민준",
        "date_of_birth": "1990-03-15",
        "role": EmployeeRole.EMPLOYEE,
    },
    {
        "employee_number": "EMP-002",
        "login_id": "emp002",
        "full_name": "김민준",
        "family_name": "김",
        "given_name": "민준",
        "date_of_birth": "1994-11-02",
        "role": EmployeeRole.EMPLOYEE,
    },
    {
        "employee_number": "EMP-003",
        "login_id": "emp003",
        "full_name": "남궁서준",
        "family_name": "남궁",
        "given_name": "서준",
        "date_of_birth": "1988-07-21",
        "role": EmployeeRole.EMPLOYEE,
    },
    {
        "employee_number": "EMP-004",
        "login_id": "emp004",
        "full_name": "황보라온",
        "family_name": "황보",
        "given_name": "라온",
        "date_of_birth": "1995-02-09",
        "role": EmployeeRole.EMPLOYEE,
    },
    {
        "employee_number": "EMP-005",
        "login_id": "emp005",
        "full_name": "김솔",
        "family_name": "김",
        "given_name": "솔",
        "date_of_birth": "1992-12-30",
        "role": EmployeeRole.EMPLOYEE,
    },
    {
        "employee_number": "EMP-006",
        "login_id": "emp006",
        "full_name": "선우진",
        "family_name": "선",
        "given_name": "우진",
        "date_of_birth": "1991-05-05",
        "role": EmployeeRole.EMPLOYEE,
    },
    {
        "employee_number": "EMP-007",
        "login_id": "emp007",
        "full_name": "이서연",
        "family_name": "이",
        "given_name": "서연",
        "date_of_birth": None,
        "role": EmployeeRole.EMPLOYEE,
    },
    {
        "employee_number": "EMP-008",
        "login_id": "emp008",
        "full_name": "박민준",
        "family_name": "박",
        "given_name": "민준",
        "date_of_birth": "1993-08-17",
        "role": EmployeeRole.EMPLOYEE,
    },
    {
        "employee_number": "EMP-009",
        "login_id": "emp009",
        "full_name": "최지우",
        "family_name": "최",
        "given_name": "지우",
        "date_of_birth": "1996-04-03",
        "role": EmployeeRole.EMPLOYEE,
    },
    {
        "employee_number": "EMP-010",
        "login_id": "emp010",
        "full_name": "정하윤",
        "family_name": "정",
        "given_name": "하윤",
        "date_of_birth": "1989-10-11",
        "role": EmployeeRole.EMPLOYEE,
    },
]


def load_seed_passwords() -> dict[str, str]:
    credentials_file = os.getenv("SEED_CREDENTIALS_FILE")
    if not credentials_file:
        raise RuntimeError("SEED_CREDENTIALS_FILE 환경 변수를 설정해 주세요.")

    path = Path(credentials_file)
    try:
        credentials = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("시드 자격증명 파일을 읽을 수 없습니다.") from error

    if not isinstance(credentials, dict):
        raise RuntimeError("시드 자격증명 파일은 JSON 객체여야 합니다.")

    passwords: dict[str, str] = {}
    for account in SEED_ACCOUNTS:
        login_id = account["login_id"]
        password = credentials.get(login_id)
        password_is_valid = (
            isinstance(password, str)
            and len(password) >= 16
            and any(character.islower() for character in password)
            and any(character.isupper() for character in password)
            and any(character.isdigit() for character in password)
            and any(not character.isalnum() for character in password)
        )
        if not password_is_valid:
            raise RuntimeError(
                f"{login_id} 계정의 비밀번호 정책을 확인해 주세요."
            )
        passwords[login_id] = password
    return passwords


def seed_accounts(db: Session) -> None:
    seed_passwords = load_seed_passwords()
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
            password_hash=hash_password(seed_passwords[account["login_id"]]),
        )
        db.add(employee)

    db.commit()
