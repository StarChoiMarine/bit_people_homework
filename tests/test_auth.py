import hashlib
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.database import Base, SessionLocal, engine
from app.core.passwords import verify_password
from app.main import app
from app.models.audit_log import AuditAction, AuditLog
from app.models.employee import Employee, EmploymentStatus
from app.models.login_session import LoginSession
from app.services import auth_service, employee_service


class AuthenticationTest(unittest.TestCase):
    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)

    def test_login_authorization_revocation_and_termination(self) -> None:
        with TestClient(app) as employee_client:
            login_response = employee_client.post(
                "/login",
                data={"login_id": "emp001", "password": "rlaalswns@@"},
                follow_redirects=False,
            )
            self.assertEqual(login_response.status_code, 303)
            self.assertEqual(login_response.headers["location"], "/employees/me")
            self.assertIn("HttpOnly", login_response.headers["set-cookie"])

            session_id = employee_client.cookies.get("session_id")
            self.assertIsNotNone(session_id)

            profile_response = employee_client.get("/employees/me")
            self.assertEqual(profile_response.status_code, 200)
            self.assertIn("김민준", profile_response.text)

            forbidden_response = employee_client.get("/admin/employees")
            self.assertEqual(forbidden_response.status_code, 403)

            nonexistent_owner_route = employee_client.get("/employees/EMP-002")
            self.assertEqual(nonexistent_owner_route.status_code, 404)

            with SessionLocal() as db:
                employee_count = db.scalar(select(func.count()).select_from(Employee))
                self.assertEqual(employee_count, 11)

                stored_session = db.get(
                    LoginSession,
                    hashlib.sha256(session_id.encode("utf-8")).hexdigest(),
                )
                self.assertIsNotNone(stored_session)
                self.assertNotEqual(stored_session.session_id_hash, session_id)

                employee = db.get(Employee, "EMP-001")
                self.assertEqual(employee.login_id, "emp001")
                self.assertNotEqual(employee.password_hash, "rlaalswns@@")

                compound_name = db.get(Employee, "EMP-003")
                self.assertEqual(compound_name.family_name, "남궁")
                self.assertEqual(compound_name.given_name, "서준")

            logout_response = employee_client.post(
                "/logout",
                follow_redirects=False,
            )
            self.assertEqual(logout_response.status_code, 303)
            self.assertEqual(employee_client.get("/employees/me").status_code, 401)

        with TestClient(app) as admin_client:
            admin_login = admin_client.post(
                "/login",
                data={"login_id": "admin", "password": "admin123"},
                follow_redirects=False,
            )
            self.assertEqual(admin_login.status_code, 303)
            self.assertEqual(admin_login.headers["location"], "/admin/employees")
            self.assertEqual(admin_client.get("/admin/employees").status_code, 200)
            self.assertEqual(
                admin_client.get("/admin/employees/EMP-004").status_code,
                200,
            )

        with (
            TestClient(app) as first_session_client,
            TestClient(app) as second_session_client,
        ):
            for client in (first_session_client, second_session_client):
                client.post(
                    "/login",
                    data={"login_id": "emp003", "password": "skarndtjwns@@"},
                )

            session_ids = [
                first_session_client.cookies.get("session_id"),
                second_session_client.cookies.get("session_id"),
            ]
            self.assertNotEqual(session_ids[0], session_ids[1])

            with SessionLocal() as db:
                revoked_count = auth_service.revoke_all_active_sessions(
                    db,
                    "EMP-003",
                )
                self.assertEqual(revoked_count, 2)
                db.rollback()

            self.assertEqual(first_session_client.get("/employees/me").status_code, 200)
            self.assertEqual(second_session_client.get("/employees/me").status_code, 200)

            with SessionLocal() as db:
                revoked_count = auth_service.revoke_all_active_sessions(
                    db,
                    "EMP-003",
                )
                self.assertEqual(revoked_count, 2)
                db.commit()

            self.assertEqual(first_session_client.get("/employees/me").status_code, 401)
            self.assertEqual(second_session_client.get("/employees/me").status_code, 401)

            with SessionLocal() as db:
                for session_id in session_ids:
                    session_id_hash = hashlib.sha256(
                        session_id.encode("utf-8")
                    ).hexdigest()
                    login_session = db.get(LoginSession, session_id_hash)
                    self.assertIsNotNone(login_session.revoked_at)

    def test_employee_creation_and_duplicate_validation(self) -> None:
        with TestClient(app) as admin_client:
            admin_client.post(
                "/login",
                data={"login_id": "admin", "password": "admin123"},
            )
            self.assertEqual(admin_client.get("/admin/employees/new").status_code, 200)

            employee_data = {
                "employee_number": "EMP-011",
                "login_id": "emp011",
                "full_name": "윤하늘",
                "family_name": "윤",
                "given_name": "하늘",
                "date_of_birth": "1997-01-02",
                "role": "EMPLOYEE",
                "password": "newpass@@",
            }
            create_response = admin_client.post(
                "/admin/employees/new",
                data=employee_data,
                follow_redirects=False,
            )
            self.assertEqual(create_response.status_code, 303)
            self.assertEqual(
                create_response.headers["location"],
                "/admin/employees/EMP-011",
            )

            with SessionLocal() as db:
                employee = db.get(Employee, "EMP-011")
                self.assertEqual(employee.login_id, "emp011")
                self.assertEqual(employee.employment_status, EmploymentStatus.ACTIVE)
                self.assertIsNone(employee.terminated_at)
                self.assertNotEqual(employee.password_hash, "newpass@@")
                self.assertTrue(verify_password("newpass@@", employee.password_hash))

                audit_log = db.scalar(
                    select(AuditLog).where(
                        AuditLog.action == AuditAction.CREATE_EMPLOYEE,
                        AuditLog.target_employee_number == "EMP-011",
                    )
                )
                self.assertEqual(audit_log.actor_employee_number, "ADM-001")
                self.assertEqual(audit_log.details["login_id"], "emp011")
                self.assertNotIn("password", audit_log.details)

            duplicate_number_data = employee_data | {
                "login_id": "another-login-id",
            }
            duplicate_number_response = admin_client.post(
                "/admin/employees/new",
                data=duplicate_number_data,
            )
            self.assertEqual(duplicate_number_response.status_code, 409)
            self.assertIn("이미 사용 중인 사번", duplicate_number_response.text)

            duplicate_login_data = employee_data | {
                "employee_number": "EMP-012",
            }
            duplicate_login_response = admin_client.post(
                "/admin/employees/new",
                data=duplicate_login_data,
            )
            self.assertEqual(duplicate_login_response.status_code, 409)
            self.assertIn("이미 사용 중인 로그인 아이디", duplicate_login_response.text)

            with SessionLocal() as db:
                employee_count = db.scalar(select(func.count()).select_from(Employee))
                self.assertEqual(employee_count, 12)
                audit_count = db.scalar(select(func.count()).select_from(AuditLog))
                self.assertEqual(audit_count, 1)

        with TestClient(app) as new_employee_client:
            login_response = new_employee_client.post(
                "/login",
                data={"login_id": "emp011", "password": "newpass@@"},
                follow_redirects=False,
            )
            self.assertEqual(login_response.status_code, 303)
            self.assertIn("윤하늘", new_employee_client.get("/employees/me").text)
            self.assertEqual(
                new_employee_client.get("/admin/employees/new").status_code,
                403,
            )

    def test_termination_is_atomic_and_immediately_blocks_access(self) -> None:
        with TestClient(app) as employee_client, TestClient(app) as admin_client:
            employee_login = employee_client.post(
                "/login",
                data={"login_id": "emp004", "password": "ghkdqhfkdhs@@"},
            )
            self.assertEqual(employee_login.status_code, 200)
            employee_session_id = employee_client.cookies.get("session_id")
            self.assertEqual(
                employee_client.post(
                    "/admin/employees/EMP-005/terminate",
                    follow_redirects=False,
                ).status_code,
                403,
            )

            admin_client.post(
                "/login",
                data={"login_id": "admin", "password": "admin123"},
            )

            self_termination_response = admin_client.post(
                "/admin/employees/ADM-001/terminate",
                follow_redirects=False,
            )
            self.assertEqual(self_termination_response.status_code, 403)
            self_detail_response = admin_client.get("/admin/employees/ADM-001")
            self.assertIn(
                "본인 계정은 퇴사 처리할 수 없습니다",
                self_detail_response.text,
            )
            with SessionLocal() as db:
                administrator = db.get(Employee, "ADM-001")
                self.assertEqual(
                    administrator.employment_status,
                    EmploymentStatus.ACTIVE,
                )
                self.assertEqual(
                    db.scalar(select(func.count()).select_from(AuditLog)),
                    0,
                )

            detail_before_termination = admin_client.get(
                "/admin/employees/EMP-004"
            )
            self.assertIn(
                "황보라온 직원을 퇴사 처리하시겠습니까?",
                detail_before_termination.text,
            )

            with SessionLocal() as db:
                with patch.object(
                    employee_service.audit_repository,
                    "add",
                    side_effect=RuntimeError("forced audit failure"),
                ):
                    with self.assertRaises(RuntimeError):
                        employee_service.terminate_employee(
                            db,
                            "EMP-004",
                            actor_employee_number="ADM-001",
                        )

            with SessionLocal() as db:
                employee = db.get(Employee, "EMP-004")
                self.assertEqual(employee.employment_status, EmploymentStatus.ACTIVE)
                self.assertIsNone(employee.terminated_at)
                session_id_hash = hashlib.sha256(
                    employee_session_id.encode("utf-8")
                ).hexdigest()
                login_session = db.get(LoginSession, session_id_hash)
                self.assertIsNone(login_session.revoked_at)
                self.assertEqual(
                    db.scalar(select(func.count()).select_from(AuditLog)),
                    0,
                )

            terminate_response = admin_client.post(
                "/admin/employees/EMP-004/terminate",
                follow_redirects=False,
            )
            self.assertEqual(terminate_response.status_code, 303)

            blocked_response = employee_client.get("/employees/me")
            self.assertEqual(blocked_response.status_code, 401)
            self.assertIn(
                auth_service.TERMINATED_ACCOUNT_MESSAGE,
                blocked_response.text,
            )

            detail_response = admin_client.get("/admin/employees/EMP-004")
            self.assertEqual(detail_response.status_code, 200)
            self.assertIn("TERMINATED", detail_response.text)
            self.assertIn("disabled", detail_response.text)

            list_response = admin_client.get("/admin/employees")
            self.assertIn("TERMINATED", list_response.text)

            with SessionLocal() as db:
                employee = db.get(Employee, "EMP-004")
                terminated_at = employee.terminated_at
                self.assertEqual(
                    employee.employment_status,
                    EmploymentStatus.TERMINATED,
                )
                self.assertIsNotNone(terminated_at)
                self.assertEqual(
                    db.scalar(select(func.count()).select_from(Employee)),
                    11,
                )

                session_id_hash = hashlib.sha256(
                    employee_session_id.encode("utf-8")
                ).hexdigest()
                login_session = db.get(LoginSession, session_id_hash)
                self.assertIsNotNone(login_session.revoked_at)

                audit_log = db.scalar(
                    select(AuditLog).where(
                        AuditLog.action == AuditAction.TERMINATE_EMPLOYEE,
                        AuditLog.target_employee_number == "EMP-004",
                    )
                )
                self.assertEqual(audit_log.actor_employee_number, "ADM-001")
                self.assertEqual(
                    audit_log.details["new_status"],
                    EmploymentStatus.TERMINATED.value,
                )

            repeated_response = admin_client.post(
                "/admin/employees/EMP-004/terminate",
                follow_redirects=False,
            )
            self.assertEqual(repeated_response.status_code, 303)

            with SessionLocal() as db:
                employee = db.get(Employee, "EMP-004")
                self.assertEqual(employee.terminated_at, terminated_at)
                self.assertEqual(
                    db.scalar(select(func.count()).select_from(AuditLog)),
                    1,
                )

        with TestClient(app) as terminated_login_client:
            login_response = terminated_login_client.post(
                "/login",
                data={"login_id": "emp004", "password": "ghkdqhfkdhs@@"},
            )
            self.assertEqual(login_response.status_code, 401)
            self.assertIn(
                auth_service.TERMINATED_ACCOUNT_MESSAGE,
                login_response.text,
            )


if __name__ == "__main__":
    unittest.main()
