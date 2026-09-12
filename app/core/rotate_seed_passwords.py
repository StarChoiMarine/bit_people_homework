from datetime import UTC, datetime

from app.core.database import SessionLocal
from app.core.passwords import hash_password
from app.core.seed import SEED_ACCOUNTS, load_seed_passwords
from app.models.audit_log import AuditAction, AuditLog
from app.repositories import audit_repository, employee_repository
from app.services import auth_service


def rotate_seed_passwords() -> tuple[int, int]:
    passwords = load_seed_passwords()
    now = datetime.now(UTC).replace(tzinfo=None)

    with SessionLocal() as db:
        employees = []
        for account in SEED_ACCOUNTS:
            employee = employee_repository.get_by_employee_number(
                db,
                account["employee_number"],
            )
            if employee is None:
                raise RuntimeError(
                    f"계정을 찾을 수 없습니다: {account['employee_number']}"
                )
            employees.append((account, employee))

        revoked_session_count = 0
        try:
            for account, employee in employees:
                employee.password_hash = hash_password(
                    passwords[account["login_id"]]
                )
                revoked_for_employee = auth_service.revoke_all_active_sessions(
                    db,
                    employee.employee_number,
                )
                revoked_session_count += revoked_for_employee
                audit_repository.add(
                    db,
                    AuditLog(
                        action=AuditAction.UPDATE_EMPLOYEE,
                        actor_employee_number="ADM-001",
                        target_employee_number=employee.employee_number,
                        created_at=now,
                        details={
                            "changed_fields": "password",
                            "sessions_revoked": str(revoked_for_employee),
                            "reason": "CREDENTIAL_EXPOSURE_ROTATION",
                        },
                    ),
                )
            db.commit()
        except Exception:
            db.rollback()
            raise

    return len(employees), revoked_session_count


def main() -> None:
    employee_count, revoked_session_count = rotate_seed_passwords()
    print(
        f"{employee_count}개 계정의 비밀번호를 교체하고 "
        f"{revoked_session_count}개 세션을 폐기했습니다."
    )


if __name__ == "__main__":
    main()
