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
from app.models.employee_change_request import (
    ChangeRequestStatus,
    EmployeeChangeRequest,
)
from app.models.login_session import LoginSession
from app.models.profile_edit_grant import ProfileEditGrant
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

    def test_profile_change_request_approval_rejection_and_audit(self) -> None:
        with TestClient(app) as employee_client, TestClient(app) as admin_client:
            employee_client.post(
                "/login",
                data={"login_id": "emp003", "password": "skarndtjwns@@"},
            )
            admin_client.post(
                "/login",
                data={"login_id": "admin", "password": "admin123"},
            )

            profile_response = employee_client.get("/employees/me")
            self.assertIn("내 정보 수정", profile_response.text)

            direct_edit_response = employee_client.get(
                "/employees/me/edit",
                follow_redirects=False,
            )
            self.assertEqual(direct_edit_response.status_code, 303)
            self.assertEqual(
                direct_edit_response.headers["location"],
                "/employees/me/edit/verify-password",
            )

            wrong_password_response = employee_client.post(
                "/employees/me/edit/verify-password",
                data={"password": "wrong-password@@"},
            )
            self.assertEqual(wrong_password_response.status_code, 401)
            self.assertIn("비밀번호가 올바르지 않습니다.", wrong_password_response.text)

            verify_response = employee_client.post(
                "/employees/me/edit/verify-password",
                data={"password": "skarndtjwns@@"},
                follow_redirects=False,
            )
            self.assertEqual(verify_response.status_code, 303)
            self.assertEqual(verify_response.headers["location"], "/employees/me/edit")

            edit_form_response = employee_client.get("/employees/me/edit")
            self.assertEqual(edit_form_response.status_code, 200)
            self.assertIn("updateFullName", edit_form_response.text)
            self.assertIn("readonly", edit_form_response.text)

            unchanged_response = employee_client.post(
                "/employees/me/edit",
                data={
                    "family_name": "남궁",
                    "given_name": "서준",
                    "date_of_birth": "1988-07-21",
                },
            )
            self.assertEqual(unchanged_response.status_code, 400)
            self.assertIn("변경된 정보가 없어", unchanged_response.text)

            with SessionLocal() as db:
                self.assertEqual(
                    db.scalar(
                        select(func.count()).select_from(EmployeeChangeRequest)
                    ),
                    0,
                )
                self.assertEqual(
                    db.scalar(select(func.count()).select_from(AuditLog)),
                    0,
                )
                self.assertEqual(
                    db.scalar(select(func.count()).select_from(ProfileEditGrant)),
                    1,
                )

            request_response = employee_client.post(
                "/employees/me/edit",
                data={
                    "family_name": "남궁",
                    "given_name": "하늘",
                    "date_of_birth": "1988-07-22",
                    "full_name": "조작된성명",
                    "employee_number": "ADM-001",
                    "role": "ADMIN",
                    "employment_status": "TERMINATED",
                },
                follow_redirects=False,
            )
            self.assertEqual(request_response.status_code, 303)
            self.assertEqual(request_response.headers["location"], "/employees/me")

            with SessionLocal() as db:
                employee = db.get(Employee, "EMP-003")
                self.assertEqual(employee.employee_number, "EMP-003")
                self.assertEqual(employee.login_id, "emp003")
                self.assertEqual(employee.full_name, "남궁서준")
                self.assertEqual(employee.family_name, "남궁")
                self.assertEqual(employee.given_name, "서준")
                self.assertEqual(employee.date_of_birth.isoformat(), "1988-07-21")
                self.assertEqual(employee.role.value, "EMPLOYEE")
                self.assertEqual(employee.employment_status, EmploymentStatus.ACTIVE)

                change_request = db.scalar(select(EmployeeChangeRequest))
                request_id = change_request.id
                self.assertEqual(change_request.status, ChangeRequestStatus.PENDING)
                self.assertEqual(change_request.requested_given_name, "하늘")
                self.assertEqual(
                    db.scalar(select(func.count()).select_from(ProfileEditGrant)),
                    0,
                )
                request_audit = db.scalar(
                    select(AuditLog).where(
                        AuditLog.action == AuditAction.REQUEST_PROFILE_CHANGE
                    )
                )
                self.assertEqual(request_audit.actor_employee_number, "EMP-003")
                self.assertEqual(request_audit.target_employee_number, "EMP-003")
                self.assertEqual(request_audit.details["request_id"], str(request_id))

            self.assertIn(
                "관리자 검토 대기 중",
                employee_client.get("/employees/me").text,
            )
            employee_list_response = admin_client.get("/admin/employees")
            self.assertIn("대기 중인 정보 변경 요청", employee_list_response.text)

            detail_response = admin_client.get("/admin/employees/EMP-003")
            self.assertIn("대기 중인 정보 변경 요청", detail_response.text)
            self.assertIn("남궁하늘", detail_response.text)

            employee_approval_attempt = employee_client.post(
                f"/admin/change-requests/{request_id}/approve",
                follow_redirects=False,
            )
            self.assertEqual(employee_approval_attempt.status_code, 403)

            approve_response = admin_client.post(
                f"/admin/change-requests/{request_id}/approve",
                follow_redirects=False,
            )
            self.assertEqual(approve_response.status_code, 303)

            with SessionLocal() as db:
                employee = db.get(Employee, "EMP-003")
                self.assertEqual(employee.full_name, "남궁하늘")
                self.assertEqual(employee.date_of_birth.isoformat(), "1988-07-22")
                approved_request = db.get(EmployeeChangeRequest, request_id)
                self.assertEqual(approved_request.status, ChangeRequestStatus.APPROVED)
                self.assertEqual(approved_request.reviewed_by, "ADM-001")
                self.assertIsNotNone(approved_request.reviewed_at)
                audit_actions = list(
                    db.scalars(select(AuditLog.action).order_by(AuditLog.id))
                )
                self.assertEqual(
                    audit_actions,
                    [
                        AuditAction.REQUEST_PROFILE_CHANGE,
                        AuditAction.APPROVE_PROFILE_CHANGE,
                    ],
                )

            repeated_approval = admin_client.post(
                f"/admin/change-requests/{request_id}/approve",
                follow_redirects=False,
            )
            self.assertEqual(repeated_approval.status_code, 409)

            employee_client.post(
                "/employees/me/edit/verify-password",
                data={"password": "skarndtjwns@@"},
            )
            employee_client.post(
                "/employees/me/edit",
                data={
                    "family_name": "남궁",
                    "given_name": "거절요청",
                    "date_of_birth": "1988-07-22",
                },
            )

            with SessionLocal() as db:
                rejected_request = db.scalar(
                    select(EmployeeChangeRequest)
                    .where(EmployeeChangeRequest.status == ChangeRequestStatus.PENDING)
                )
                rejected_request_id = rejected_request.id

            reject_response = admin_client.post(
                f"/admin/change-requests/{rejected_request_id}/reject",
                follow_redirects=False,
            )
            self.assertEqual(reject_response.status_code, 303)

            with SessionLocal() as db:
                employee = db.get(Employee, "EMP-003")
                self.assertEqual(employee.full_name, "남궁하늘")
                rejected_request = db.get(
                    EmployeeChangeRequest,
                    rejected_request_id,
                )
                self.assertEqual(rejected_request.status, ChangeRequestStatus.REJECTED)
                self.assertIsNone(rejected_request.employee_acknowledged_at)
                audit_actions = list(
                    db.scalars(select(AuditLog.action).order_by(AuditLog.id))
                )
                self.assertEqual(
                    audit_actions,
                    [
                        AuditAction.REQUEST_PROFILE_CHANGE,
                        AuditAction.APPROVE_PROFILE_CHANGE,
                        AuditAction.REQUEST_PROFILE_CHANGE,
                        AuditAction.REJECT_PROFILE_CHANGE,
                    ],
                )

            rejection_notice = employee_client.get("/employees/me")
            self.assertIn(
                "최근 정보수정 요청이 거절되었습니다. 관리자에게 문의하세요.",
                rejection_notice.text,
            )
            self.assertEqual(
                admin_client.post(
                    "/employees/me/change-request-notice/dismiss",
                    follow_redirects=False,
                ).status_code,
                403,
            )

            dismiss_response = employee_client.post(
                "/employees/me/change-request-notice/dismiss",
                follow_redirects=False,
            )
            self.assertEqual(dismiss_response.status_code, 303)
            self.assertEqual(dismiss_response.headers["location"], "/employees/me")
            self.assertNotIn(
                "최근 정보수정 요청이 거절되었습니다. 관리자에게 문의하세요.",
                employee_client.get("/employees/me").text,
            )

            with SessionLocal() as db:
                rejected_request = db.get(
                    EmployeeChangeRequest,
                    rejected_request_id,
                )
                self.assertEqual(rejected_request.status, ChangeRequestStatus.REJECTED)
                self.assertIsNotNone(rejected_request.employee_acknowledged_at)
                dismiss_audit = db.scalar(
                    select(AuditLog).where(
                        AuditLog.action
                        == AuditAction.DISMISS_PROFILE_CHANGE_NOTICE
                    )
                )
                self.assertEqual(dismiss_audit.actor_employee_number, "EMP-003")
                self.assertEqual(dismiss_audit.target_employee_number, "EMP-003")
                self.assertEqual(dismiss_audit.details["acknowledged_count"], "1")

            employee_client.post(
                "/employees/me/change-request-notice/dismiss",
                follow_redirects=False,
            )
            with SessionLocal() as db:
                dismiss_audit_count = db.scalar(
                    select(func.count())
                    .select_from(AuditLog)
                    .where(
                        AuditLog.action
                        == AuditAction.DISMISS_PROFILE_CHANGE_NOTICE
                    )
                )
                self.assertEqual(dismiss_audit_count, 1)

    def test_password_change_validation_audit_and_other_session_revocation(self) -> None:
        with (
            TestClient(app) as current_client,
            TestClient(app) as other_client,
        ):
            for client in (current_client, other_client):
                client.post(
                    "/login",
                    data={"login_id": "emp005", "password": "rlathf@@"},
                )

            password_form = current_client.get("/employees/me/password")
            self.assertEqual(password_form.status_code, 200)
            self.assertIn("새 비밀번호 확인", password_form.text)

            wrong_current_password = current_client.post(
                "/employees/me/password",
                data={
                    "current_password": "wrong-password@@",
                    "new_password": "changed@@123",
                    "new_password_confirmation": "changed@@123",
                },
            )
            self.assertEqual(wrong_current_password.status_code, 400)
            self.assertIn("현재 비밀번호가 올바르지 않습니다.", wrong_current_password.text)

            mismatched_password = current_client.post(
                "/employees/me/password",
                data={
                    "current_password": "rlathf@@",
                    "new_password": "changed@@123",
                    "new_password_confirmation": "different@@123",
                },
            )
            self.assertEqual(mismatched_password.status_code, 400)
            self.assertIn("서로 일치하지 않습니다.", mismatched_password.text)

            change_response = current_client.post(
                "/employees/me/password",
                data={
                    "current_password": "rlathf@@",
                    "new_password": "changed@@123",
                    "new_password_confirmation": "changed@@123",
                },
                follow_redirects=False,
            )
            self.assertEqual(change_response.status_code, 303)
            self.assertEqual(current_client.get("/employees/me").status_code, 200)
            self.assertEqual(other_client.get("/employees/me").status_code, 401)

            with SessionLocal() as db:
                employee = db.get(Employee, "EMP-005")
                self.assertTrue(verify_password("changed@@123", employee.password_hash))
                password_audit = db.scalar(
                    select(AuditLog).where(
                        AuditLog.action == AuditAction.CHANGE_PASSWORD
                    )
                )
                self.assertEqual(password_audit.actor_employee_number, "EMP-005")
                self.assertNotIn("password", password_audit.details)

        with TestClient(app) as login_client:
            old_password_login = login_client.post(
                "/login",
                data={"login_id": "emp005", "password": "rlathf@@"},
            )
            self.assertEqual(old_password_login.status_code, 401)

            new_password_login = login_client.post(
                "/login",
                data={"login_id": "emp005", "password": "changed@@123"},
                follow_redirects=False,
            )
            self.assertEqual(new_password_login.status_code, 303)


if __name__ == "__main__":
    unittest.main()
