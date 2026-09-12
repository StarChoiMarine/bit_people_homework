import asyncio
import json
import unittest
from collections import deque
from datetime import datetime, timedelta

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.clients.background_check_client import (
    BackgroundCheckResponse,
    HistoryCheck,
    HttpBackgroundCheckClient,
)
from app.core.database import Base, SessionLocal, engine
from app.main import app
from app.models.audit_log import AuditAction, AuditLog
from app.models.background_check import (
    BackgroundCheckRequest,
    BackgroundCheckResult,
    BackgroundCheckResultValue,
    BackgroundCheckWorkflowStatus,
    ResultDeletionReason,
)
from app.models.employee import Employee
from app.services import background_check_service, employee_service
from app.services.background_check_processor import BackgroundCheckProcessor


class MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current

    def advance(self, **values: int) -> None:
        self.current += timedelta(**values)


class FakeBackgroundCheckClient:
    def __init__(self) -> None:
        self.create_responses: deque[BackgroundCheckResponse] = deque()
        self.get_responses: deque[BackgroundCheckResponse] = deque()
        self.list_responses: deque[BackgroundCheckResponse] = deque()
        self.create_calls: list[dict[str, str]] = []
        self.get_calls: list[str] = []
        self.list_calls: list[str] = []

    async def create_check(
        self,
        employee_id: str,
        first_name: str,
        last_name: str,
        date_of_birth: str,
    ) -> BackgroundCheckResponse:
        self.create_calls.append(
            {
                "employee_id": employee_id,
                "first_name": first_name,
                "last_name": last_name,
                "date_of_birth": date_of_birth,
            }
        )
        return self.create_responses.popleft()

    async def get_check(self, check_id: str) -> BackgroundCheckResponse:
        self.get_calls.append(check_id)
        return self.get_responses.popleft()

    async def list_checks(self, employee_id: str) -> BackgroundCheckResponse:
        self.list_calls.append(employee_id)
        return self.list_responses.popleft()


class SlowFakeBackgroundCheckClient(FakeBackgroundCheckClient):
    def __init__(self) -> None:
        super().__init__()
        self.active_calls = 0
        self.maximum_active_calls = 0

    async def create_check(
        self,
        employee_id: str,
        first_name: str,
        last_name: str,
        date_of_birth: str,
    ) -> BackgroundCheckResponse:
        self.create_calls.append(
            {
                "employee_id": employee_id,
                "first_name": first_name,
                "last_name": last_name,
                "date_of_birth": date_of_birth,
            }
        )
        self.active_calls += 1
        self.maximum_active_calls = max(
            self.maximum_active_calls,
            self.active_calls,
        )
        await asyncio.sleep(0.02)
        self.active_calls -= 1
        return BackgroundCheckResponse(
            status_code=201,
            check_id=f"CHK-{employee_id}",
            employee_id=employee_id,
            status="pending",
        )


class BackgroundCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)

    def _create_request(
        self,
        employee_number: str,
        now: datetime,
    ) -> int:
        with SessionLocal() as db:
            request = background_check_service.create_request(
                db=db,
                employee_number=employee_number,
                requested_by_employee_number="ADM-001",
                request_reason="채용 전 필수 확인",
                now=now,
            )
            return request.id

    def test_admin_request_view_auto_acknowledge_and_sensitive_data_minimization(
        self,
    ) -> None:
        clock = MutableClock(datetime(2026, 9, 12, 9, 0, 0))
        fake_client = FakeBackgroundCheckClient()
        fake_client.create_responses.append(
            BackgroundCheckResponse(
                status_code=201,
                check_id="CHK-CLEAR-001",
                employee_id="EMP-003",
                status="clear",
            )
        )

        with TestClient(app) as admin_client, TestClient(app) as employee_client:
            admin_client.post(
                "/login",
                data={"login_id": "admin", "password": "admin123"},
            )
            employee_client.post(
                "/login",
                data={"login_id": "emp003", "password": "skarndtjwns@@"},
            )

            detail = admin_client.get("/admin/employees/EMP-003")
            self.assertIn("요청과 결과 열람은", detail.text)
            self.assertIn("요청 사유", detail.text)
            self.assertIn("required", detail.text)

            employee_attempt = employee_client.post(
                "/admin/employees/EMP-003/background-checks",
                data={"request_reason": "권한 없는 요청"},
            )
            self.assertEqual(employee_attempt.status_code, 403)

            missing_reason = admin_client.post(
                "/admin/employees/EMP-003/background-checks",
                data={"request_reason": "   "},
            )
            self.assertEqual(missing_reason.status_code, 400)
            self.assertIn("요청 사유를 입력", missing_reason.text)

            unknown_birth_date = admin_client.post(
                "/admin/employees/EMP-007/background-checks",
                data={"request_reason": "정기 확인"},
            )
            self.assertEqual(unknown_birth_date.status_code, 400)
            self.assertIn("생년월일이 확인되지 않아", unknown_birth_date.text)

            create_response = admin_client.post(
                "/admin/employees/EMP-003/background-checks",
                data={"request_reason": "  채용 전 필수 확인  "},
                follow_redirects=False,
            )
            self.assertEqual(create_response.status_code, 303)

            with SessionLocal() as db:
                request = db.scalar(select(BackgroundCheckRequest))
                request_id = request.id
                self.assertEqual(request.request_reason, "채용 전 필수 확인")
                self.assertEqual(request.status, BackgroundCheckWorkflowStatus.REQUESTED)

            processor = BackgroundCheckProcessor(
                fake_client,
                now_provider=clock.now,
            )
            asyncio.run(processor.process_due_once())

            self.assertEqual(len(fake_client.create_calls), 1)
            self.assertEqual(
                fake_client.create_calls[0],
                {
                    "employee_id": "EMP-003",
                    "first_name": "서준",
                    "last_name": "남궁",
                    "date_of_birth": "1988-07-21",
                },
            )

            with engine.connect() as connection:
                result_columns = {
                    column["name"]
                    for column in connection.exec_driver_sql(
                        "PRAGMA table_info(background_check_results)"
                    ).mappings()
                }
            self.assertEqual(
                result_columns,
                {"request_id", "result", "created_at", "expires_at"},
            )

            with SessionLocal() as db:
                result = db.get(BackgroundCheckResult, request_id)
                self.assertEqual(result.result, BackgroundCheckResultValue.CLEAR)
                request = db.get(BackgroundCheckRequest, request_id)
                self.assertEqual(request.status, BackgroundCheckWorkflowStatus.COMPLETED)
                self.assertFalse(hasattr(request, "criminal_record"))
                self.assertFalse(hasattr(result, "credit_score"))

            employee_view_attempt = employee_client.post(
                f"/admin/background-check-requests/{request_id}/view",
                data={"access_reason": "권한 없는 열람"},
            )
            self.assertEqual(employee_view_attempt.status_code, 403)

            missing_access_reason = admin_client.post(
                f"/admin/background-check-requests/{request_id}/view",
                data={"access_reason": ""},
            )
            self.assertEqual(missing_access_reason.status_code, 400)
            self.assertIn("열람 사유를 입력", missing_access_reason.text)

            view_response = admin_client.post(
                f"/admin/background-check-requests/{request_id}/view",
                data={"access_reason": "인사 적합성 검토"},
            )
            self.assertEqual(view_response.status_code, 200)
            self.assertEqual(view_response.headers["cache-control"], "no-store")
            self.assertIn("CLEAR", view_response.text)
            self.assertIn("감사 로그에 기록되었습니다", view_response.text)
            self.assertIn("열람과 동시에 서버에서 삭제", view_response.text)
            self.assertIn("확인 및 정보파기", view_response.text)
            self.assertNotIn("직원 목록으로 이동", view_response.text)
            self.assertNotIn("criminalRecord", view_response.text)
            self.assertNotIn("creditScore", view_response.text)

            with SessionLocal() as db:
                request_audit = db.scalar(
                    select(AuditLog).where(
                        AuditLog.action == AuditAction.REQUEST_BACKGROUND_CHECK
                    )
                )
                view_audit = db.scalar(
                    select(AuditLog).where(
                        AuditLog.action == AuditAction.VIEW_BACKGROUND_CHECK_RESULT
                    )
                )
                acknowledge_audit = db.scalar(
                    select(AuditLog).where(
                        AuditLog.action
                        == AuditAction.ACKNOWLEDGE_BACKGROUND_CHECK_RESULT
                    )
                )
                self.assertEqual(request_audit.details, {"request_id": str(request_id)})
                self.assertEqual(view_audit.details["access_reason"], "인사 적합성 검토")
                self.assertEqual(
                    acknowledge_audit.details,
                    {"request_id": str(request_id)},
                )
                audit_text = json.dumps(
                    [
                        request_audit.details,
                        view_audit.details,
                        acknowledge_audit.details,
                    ],
                    ensure_ascii=False,
                )
                self.assertNotIn("CLEAR", audit_text)
                self.assertNotIn("criminal", audit_text.lower())
                self.assertNotIn("credit", audit_text.lower())

                self.assertIsNone(db.get(BackgroundCheckResult, request_id))
                background_request = db.get(BackgroundCheckRequest, request_id)
                self.assertEqual(
                    background_request.result_deletion_reason,
                    ResultDeletionReason.ACKNOWLEDGED,
                )
                self.assertIsNotNone(background_request.result_deleted_at)

            detail_after_view = admin_client.get("/admin/employees/EMP-003")
            self.assertIn("확인 완료로 삭제됨", detail_after_view.text)

            home_after_view = admin_client.get("/", follow_redirects=False)
            self.assertEqual(home_after_view.status_code, 303)

            view_after_acknowledgement = admin_client.post(
                f"/admin/background-check-requests/{request_id}/view",
                data={"access_reason": "뒤로가기 재확인"},
            )
            self.assertEqual(view_after_acknowledgement.status_code, 410)
            self.assertIn("확인 완료로 삭제됨", view_after_acknowledgement.text)
            self.assertNotIn(">CLEAR<", view_after_acknowledgement.text)

            list_after_acknowledgement = admin_client.get("/admin/employees")
            row_start = list_after_acknowledgement.text.index("<td>EMP-003</td>")
            row_end = list_after_acknowledgement.text.index("</tr>", row_start)
            acknowledged_employee_row = list_after_acknowledgement.text[
                row_start:row_end
            ]
            self.assertNotIn("text-bg-danger", acknowledged_employee_row)

            with SessionLocal() as db:
                self.assertIsNone(db.get(BackgroundCheckResult, request_id))
                request = db.get(BackgroundCheckRequest, request_id)
                self.assertEqual(
                    request.result_deletion_reason,
                    ResultDeletionReason.ACKNOWLEDGED,
                )
                self.assertIsNotNone(request.result_deleted_at)
                self.assertEqual(
                    db.scalar(select(func.count()).select_from(Employee)),
                    11,
                )

    def test_pending_ui_status_api_and_unified_attention_badge(self) -> None:
        clock = MutableClock(datetime(2026, 9, 12, 9, 30, 0))
        fake_client = FakeBackgroundCheckClient()
        fake_client.create_responses.append(
            BackgroundCheckResponse(
                status_code=201,
                check_id="CHK-POLL-UI",
                employee_id="EMP-008",
                status="pending",
            )
        )

        with TestClient(app) as admin_client, TestClient(app) as employee_client:
            admin_client.post(
                "/login",
                data={"login_id": "admin", "password": "admin123"},
            )
            employee_client.post(
                "/login",
                data={"login_id": "emp008", "password": "qkralswns@@"},
            )
            create_response = admin_client.post(
                "/admin/employees/EMP-008/background-checks",
                data={"request_reason": "입사 서류 확인"},
                follow_redirects=False,
            )
            self.assertEqual(create_response.status_code, 303)

            with SessionLocal() as db:
                request_id = db.scalar(select(BackgroundCheckRequest.id))

            processor = BackgroundCheckProcessor(
                fake_client,
                now_provider=clock.now,
            )
            asyncio.run(processor.process_due_once())

            detail = admin_client.get("/admin/employees/EMP-008")
            self.assertIn("평균 약 3분", detail.text)
            self.assertIn("대부분 5분 이내", detail.text)
            self.assertIn("pollBackgroundCheckStatus", detail.text)
            self.assertIn("pollBackgroundCheckStatus, 2000", detail.text)
            self.assertIn("pollBackgroundCheckStatus, 5000", detail.text)

            employee_status_attempt = employee_client.get(
                f"/admin/background-check-requests/{request_id}/status"
            )
            self.assertEqual(employee_status_attempt.status_code, 403)

            pending_status = admin_client.get(
                f"/admin/background-check-requests/{request_id}/status"
            )
            self.assertEqual(pending_status.status_code, 200)
            self.assertEqual(pending_status.headers["cache-control"], "no-store")
            self.assertEqual(
                pending_status.json(),
                {
                    "status": "PENDING",
                    "is_final": False,
                    "result_available": False,
                },
            )

            fake_client.get_responses.append(
                BackgroundCheckResponse(
                    status_code=200,
                    check_id="CHK-POLL-UI",
                    employee_id="EMP-008",
                    status="flagged",
                )
            )
            clock.advance(seconds=5)
            asyncio.run(processor.process_due_once())

            completed_status = admin_client.get(
                f"/admin/background-check-requests/{request_id}/status"
            )
            self.assertEqual(
                completed_status.json(),
                {
                    "status": "COMPLETED",
                    "is_final": True,
                    "result_available": True,
                },
            )
            self.assertNotIn("CLEAR", completed_status.text)
            self.assertNotIn("FLAGGED", completed_status.text)

            employee_list = admin_client.get("/admin/employees")
            employee_row_start = employee_list.text.index("<td>EMP-008</td>")
            employee_row_end = employee_list.text.index("</tr>", employee_row_start)
            employee_row = employee_list.text[employee_row_start:employee_row_end]
            self.assertIn("확인 필요", employee_row)
            self.assertNotIn("CLEAR", employee_list.text)
            self.assertNotIn("FLAGGED", employee_list.text)

    def test_post_timeout_is_not_retried_and_history_reconciles(self) -> None:
        with TestClient(app):
            clock = MutableClock(datetime(2026, 9, 12, 10, 0, 0))
            request_id = self._create_request("EMP-004", clock.now())
            fake_client = FakeBackgroundCheckClient()
            fake_client.create_responses.append(
                BackgroundCheckResponse(None, error_code="TIMEOUT")
            )
            processor = BackgroundCheckProcessor(fake_client, now_provider=clock.now)

            asyncio.run(processor.process_due_once())
            with SessionLocal() as db:
                request = db.get(BackgroundCheckRequest, request_id)
                self.assertEqual(
                    request.status,
                    BackgroundCheckWorkflowStatus.SUBMISSION_UNKNOWN,
                )
            self.assertEqual(len(fake_client.create_calls), 1)

            clock.advance(seconds=5)
            fake_client.list_responses.append(
                BackgroundCheckResponse(
                    status_code=200,
                    employee_id="EMP-004",
                    checks=(
                        HistoryCheck(
                            check_id="CHK-RECOVERED",
                            status="flagged",
                            created_at=datetime(2026, 9, 12, 10, 0, 0),
                        ),
                    ),
                )
            )
            asyncio.run(processor.process_due_once())

            self.assertEqual(len(fake_client.create_calls), 1)
            self.assertEqual(fake_client.list_calls, ["EMP-004"])
            with SessionLocal() as db:
                request = db.get(BackgroundCheckRequest, request_id)
                result = db.get(BackgroundCheckResult, request_id)
                self.assertEqual(request.external_check_id, "CHK-RECOVERED")
                self.assertEqual(request.status, BackgroundCheckWorkflowStatus.COMPLETED)
                self.assertEqual(result.result, BackgroundCheckResultValue.FLAGGED)

    def test_get_retry_503_delay_tracking_limit_and_ttl(self) -> None:
        with TestClient(app):
            clock = MutableClock(datetime(2026, 9, 12, 11, 0, 0))
            request_id = self._create_request("EMP-005", clock.now())
            fake_client = FakeBackgroundCheckClient()
            fake_client.create_responses.append(
                BackgroundCheckResponse(
                    status_code=201,
                    check_id="CHK-PENDING",
                    employee_id="EMP-005",
                    status="pending",
                )
            )
            fake_client.get_responses.extend(
                [
                    BackgroundCheckResponse(status_code=500),
                    BackgroundCheckResponse(
                        status_code=503,
                        retry_after_seconds=17,
                    ),
                ]
            )
            processor = BackgroundCheckProcessor(fake_client, now_provider=clock.now)

            asyncio.run(processor.process_due_once())
            clock.advance(seconds=5)
            asyncio.run(processor.process_due_once())
            with SessionLocal() as db:
                request = db.get(BackgroundCheckRequest, request_id)
                self.assertEqual(request.next_poll_at, clock.now() + timedelta(seconds=5))
                self.assertEqual(request.get_attempt_count, 1)

            clock.advance(seconds=5)
            asyncio.run(processor.process_due_once())
            with SessionLocal() as db:
                request = db.get(BackgroundCheckRequest, request_id)
                self.assertEqual(request.next_poll_at, clock.now() + timedelta(seconds=17))
                self.assertEqual(request.get_attempt_count, 2)
                request.tracking_started_at = clock.now() - timedelta(seconds=300)
                request.next_poll_at = clock.now()
                db.commit()

            asyncio.run(processor.process_due_once())
            self.assertEqual(len(fake_client.get_calls), 2)
            with SessionLocal() as db:
                request = db.get(BackgroundCheckRequest, request_id)
                self.assertEqual(request.status, BackgroundCheckWorkflowStatus.PENDING)
                self.assertIsNotNone(request.automatic_polling_stopped_at)

            original_submission_started_at = request.submission_started_at
            with SessionLocal() as db:
                background_check_service.resume_safe_lookup(
                    db,
                    request_id,
                    now=clock.now(),
                )
                request = db.get(BackgroundCheckRequest, request_id)
                self.assertEqual(
                    request.submission_started_at,
                    original_submission_started_at,
                )
                self.assertEqual(request.tracking_started_at, clock.now())
                self.assertEqual(request.get_attempt_count, 0)
                self.assertIsNone(request.automatic_polling_stopped_at)
                request.get_attempt_count = 60
                db.commit()

            asyncio.run(processor.process_due_once())
            self.assertEqual(len(fake_client.get_calls), 2)
            with SessionLocal() as db:
                request = db.get(BackgroundCheckRequest, request_id)
                self.assertIsNotNone(request.automatic_polling_stopped_at)

            completed_id = self._create_request("EMP-006", clock.now())
            ttl_client = FakeBackgroundCheckClient()
            ttl_client.create_responses.append(
                BackgroundCheckResponse(
                    status_code=201,
                    check_id="CHK-TTL",
                    employee_id="EMP-006",
                    status="clear",
                )
            )
            ttl_processor = BackgroundCheckProcessor(
                ttl_client,
                now_provider=clock.now,
            )
            asyncio.run(ttl_processor.process_due_once())

            with SessionLocal() as db:
                employee_service.terminate_employee(
                    db,
                    "EMP-006",
                    actor_employee_number="ADM-001",
                )
                self.assertIsNotNone(db.get(BackgroundCheckResult, completed_id))

            clock.advance(hours=24)

            with SessionLocal() as db:
                deleted_count = background_check_service.purge_expired_results(
                    db,
                    clock.now(),
                )
                self.assertEqual(deleted_count, 1)
                self.assertIsNone(db.get(BackgroundCheckResult, completed_id))
                completed_request = db.get(BackgroundCheckRequest, completed_id)
                self.assertEqual(
                    completed_request.result_deletion_reason,
                    ResultDeletionReason.TTL_EXPIRED,
                )
                self.assertEqual(
                    db.scalar(select(func.count()).select_from(BackgroundCheckRequest)),
                    2,
                )
                self.assertEqual(
                    db.scalar(select(func.count()).select_from(Employee)),
                    11,
                )

    def test_external_client_ignores_details_and_retry_after_priority(self) -> None:
        responses = deque(
            [
                httpx.Response(
                    201,
                    json={
                        "checkId": "CHK-CREATED",
                        "employeeId": "EMP-001",
                        "status": "pending",
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "checkId": "CHK-DETAIL",
                        "employeeId": "EMP-001",
                        "status": "flagged",
                        "criminalRecord": True,
                        "educationVerified": False,
                        "employmentVerified": False,
                        "creditScore": "poor",
                    },
                ),
                httpx.Response(
                    503,
                    headers={"Retry-After": "17"},
                    json={"retryAfter": 30, "criminalRecord": True},
                ),
                httpx.Response(503, json={"retryAfter": 30}),
                httpx.Response(503, json={}),
            ]
        )
        observed_timeouts: list[dict[str, float]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            observed_timeouts.append(request.extensions["timeout"])
            return responses.popleft()

        async def exercise_client():
            transport = httpx.MockTransport(handler)
            async with HttpBackgroundCheckClient(
                base_url="https://background-check.test",
                transport=transport,
            ) as client:
                created = await client.create_check(
                    employee_id="EMP-001",
                    first_name="민준",
                    last_name="김",
                    date_of_birth="1990-03-15",
                )
                detail = await client.get_check("CHK-DETAIL")
                header_retry = await client.get_check("CHK-HEADER")
                body_retry = await client.get_check("CHK-BODY")
                fallback_retry = await client.get_check("CHK-FALLBACK")
                return created, detail, header_retry, body_retry, fallback_retry

        created, detail, header_retry, body_retry, fallback_retry = asyncio.run(
            exercise_client()
        )
        self.assertEqual(created.status, "pending")
        self.assertEqual(detail.status, "flagged")
        self.assertFalse(hasattr(detail, "criminal_record"))
        self.assertFalse(hasattr(detail, "credit_score"))
        self.assertNotIn("poor", repr(detail))
        self.assertEqual(header_retry.retry_after_seconds, 17)
        self.assertEqual(body_retry.retry_after_seconds, 30)
        self.assertIsNone(fallback_retry.retry_after_seconds)
        self.assertEqual(
            BackgroundCheckProcessor._retry_delay(fallback_retry),
            timedelta(seconds=30),
        )
        self.assertEqual(observed_timeouts[0]["read"], 5.0)
        self.assertEqual(observed_timeouts[1]["read"], 35.0)

    def test_external_concurrency_is_limited_to_five(self) -> None:
        with TestClient(app):
            now = datetime(2026, 9, 12, 12, 0, 0)
            for employee_number in (
                "EMP-001",
                "EMP-002",
                "EMP-003",
                "EMP-004",
                "EMP-005",
                "EMP-006",
            ):
                self._create_request(employee_number, now)

            fake_client = SlowFakeBackgroundCheckClient()
            processor = BackgroundCheckProcessor(
                fake_client,
                now_provider=lambda: now,
            )
            asyncio.run(processor.process_due_once())

            self.assertEqual(len(fake_client.create_calls), 6)
            self.assertEqual(fake_client.maximum_active_calls, 5)


if __name__ == "__main__":
    unittest.main()
