import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from app.clients.background_check_client import (
    BackgroundCheckClient,
    BackgroundCheckResponse,
    HttpBackgroundCheckClient,
)
from app.core.database import SessionLocal
from app.models.background_check import (
    BackgroundCheckRequest,
    BackgroundCheckResult,
    BackgroundCheckResultValue,
    BackgroundCheckWorkflowStatus,
)
from app.repositories import background_check_repository
from app.services import background_check_service


GET_RETRY_INTERVAL = timedelta(seconds=5)
DEFAULT_503_RETRY_INTERVAL = timedelta(seconds=30)
AUTOMATIC_TRACKING_WINDOW = timedelta(seconds=300)
RESULT_TTL = timedelta(hours=24)
MAX_GET_ATTEMPTS = 60
RECONCILIATION_CLOCK_SKEW = timedelta(seconds=30)
MAX_CONCURRENT_EXTERNAL_CALLS = 5


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class BackgroundCheckProcessor:
    def __init__(
        self,
        client: BackgroundCheckClient,
        session_factory: sessionmaker[Session] = SessionLocal,
        now_provider: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.client = client
        self.session_factory = session_factory
        self.now_provider = now_provider
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXTERNAL_CALLS)

    async def process_due_once(self) -> int:
        now = self.now_provider()
        with self.session_factory() as db:
            background_check_service.purge_expired_results(db, now)
            request_ids = background_check_repository.list_due_request_ids(db, now)
        if not request_ids:
            return 0
        await asyncio.gather(*(self._process_request(item) for item in request_ids))
        return len(request_ids)

    async def _process_request(self, request_id: int) -> None:
        with self.session_factory() as db:
            background_request = background_check_repository.get_request(db, request_id)
            if background_request is None:
                return
            status = background_request.status

        if status == BackgroundCheckWorkflowStatus.REQUESTED:
            await self._submit_request(request_id)
        elif status == BackgroundCheckWorkflowStatus.SUBMISSION_UNKNOWN:
            await self._reconcile_unknown_request(request_id)
        elif status == BackgroundCheckWorkflowStatus.PENDING:
            await self._poll_pending_request(request_id)

    async def _submit_request(self, request_id: int) -> None:
        now = self.now_provider()
        with self.session_factory() as db:
            background_request = background_check_repository.get_request(db, request_id)
            if (
                background_request is None
                or background_request.status
                != BackgroundCheckWorkflowStatus.REQUESTED
            ):
                return
            if background_request.submission_started_at is not None:
                background_request.status = (
                    BackgroundCheckWorkflowStatus.SUBMISSION_UNKNOWN
                )
                background_request.next_poll_at = now
                background_request.last_error_code = "INTERRUPTED_SUBMISSION"
                db.commit()
                return

            background_request.submission_started_at = now
            background_request.tracking_started_at = now
            db.commit()
            employee_id = background_request.employee_number
            first_name = background_request.submitted_given_name
            last_name = background_request.submitted_family_name
            date_of_birth = background_request.submitted_date_of_birth.isoformat()

        async with self.semaphore:
            response = await self.client.create_check(
                employee_id=employee_id,
                first_name=first_name,
                last_name=last_name,
                date_of_birth=date_of_birth,
            )
        self._apply_submission_response(request_id, employee_id, response)

    def _apply_submission_response(
        self,
        request_id: int,
        employee_id: str,
        response: BackgroundCheckResponse,
    ) -> None:
        now = self.now_provider()
        with self.session_factory() as db:
            background_request = background_check_repository.get_request(db, request_id)
            if background_request is None:
                return

            if response.status_code == 400:
                self._mark_failed(background_request, now, "HTTP_400")
            elif (
                response.status_code == 201
                and response.employee_id == employee_id
                and response.check_id
                and response.status in {"pending", "clear", "flagged"}
            ):
                background_request.external_check_id = response.check_id
                if response.status == "pending":
                    background_request.status = BackgroundCheckWorkflowStatus.PENDING
                    background_request.next_poll_at = now + GET_RETRY_INTERVAL
                    background_request.last_error_code = None
                else:
                    self._complete_request(db, background_request, response.status, now)
            else:
                background_request.status = (
                    BackgroundCheckWorkflowStatus.SUBMISSION_UNKNOWN
                )
                background_request.next_poll_at = now + self._retry_delay(response)
                background_request.last_error_code = self._error_code(response)
            db.commit()

    async def _reconcile_unknown_request(self, request_id: int) -> None:
        now = self.now_provider()
        with self.session_factory() as db:
            background_request = background_check_repository.get_request(db, request_id)
            if background_request is None or self._should_stop(background_request, now):
                if background_request is not None:
                    self._stop_automatic_polling(background_request, now)
                    db.commit()
                return
            employee_id = background_request.employee_number

        async with self.semaphore:
            response = await self.client.list_checks(employee_id)

        with self.session_factory() as db:
            background_request = background_check_repository.get_request(db, request_id)
            if background_request is None:
                return
            background_request.get_attempt_count += 1
            if response.status_code == 200 and response.employee_id == employee_id:
                known_ids = background_check_repository.list_known_external_check_ids(db)
                started_at = background_request.submission_started_at
                candidates = [
                    item
                    for item in response.checks
                    if item.check_id not in known_ids
                    and item.created_at is not None
                    and started_at is not None
                    and started_at - RECONCILIATION_CLOCK_SKEW
                    <= item.created_at
                    <= now + RECONCILIATION_CLOCK_SKEW
                ]
                if len(candidates) == 1:
                    candidate = candidates[0]
                    if candidate.status in {"clear", "flagged"}:
                        background_request.external_check_id = candidate.check_id
                        self._complete_request(
                            db,
                            background_request,
                            candidate.status,
                            now,
                        )
                    elif candidate.status == "pending":
                        background_request.external_check_id = candidate.check_id
                        background_request.status = (
                            BackgroundCheckWorkflowStatus.PENDING
                        )
                        background_request.next_poll_at = now + GET_RETRY_INTERVAL
                        background_request.last_error_code = None
                    else:
                        background_request.next_poll_at = now + GET_RETRY_INTERVAL
                        background_request.last_error_code = "INVALID_HISTORY_STATUS"
                else:
                    background_request.next_poll_at = now + GET_RETRY_INTERVAL
                    background_request.last_error_code = (
                        "NO_RECONCILIATION_MATCH"
                        if not candidates
                        else "AMBIGUOUS_RECONCILIATION"
                    )
            elif response.status_code == 400:
                self._mark_failed(background_request, now, "HTTP_400")
            elif response.status_code == 404:
                self._stop_automatic_polling(background_request, now, "HTTP_404")
            else:
                background_request.next_poll_at = now + self._retry_delay(response)
                background_request.last_error_code = self._error_code(response)
            db.commit()

    async def _poll_pending_request(self, request_id: int) -> None:
        now = self.now_provider()
        with self.session_factory() as db:
            background_request = background_check_repository.get_request(db, request_id)
            if background_request is None or self._should_stop(background_request, now):
                if background_request is not None:
                    self._stop_automatic_polling(background_request, now)
                    db.commit()
                return
            if background_request.external_check_id is None:
                background_request.status = (
                    BackgroundCheckWorkflowStatus.SUBMISSION_UNKNOWN
                )
                background_request.next_poll_at = now
                background_request.last_error_code = "MISSING_CHECK_ID"
                db.commit()
                return
            check_id = background_request.external_check_id
            employee_id = background_request.employee_number

        async with self.semaphore:
            response = await self.client.get_check(check_id)

        with self.session_factory() as db:
            background_request = background_check_repository.get_request(db, request_id)
            if background_request is None:
                return
            background_request.get_attempt_count += 1
            if (
                response.status_code == 200
                and response.check_id == check_id
                and response.employee_id == employee_id
                and response.status in {"pending", "clear", "flagged"}
            ):
                if response.status == "pending":
                    background_request.next_poll_at = now + GET_RETRY_INTERVAL
                    background_request.last_error_code = None
                else:
                    self._complete_request(
                        db,
                        background_request,
                        response.status,
                        now,
                    )
            elif response.status_code == 400:
                self._mark_failed(background_request, now, "HTTP_400")
            elif response.status_code == 404:
                self._stop_automatic_polling(background_request, now, "HTTP_404")
            else:
                background_request.next_poll_at = now + self._retry_delay(response)
                background_request.last_error_code = self._error_code(response)
            db.commit()

    @staticmethod
    def _complete_request(
        db: Session,
        background_request: BackgroundCheckRequest,
        external_status: str,
        now: datetime,
    ) -> None:
        result_value = BackgroundCheckResultValue(external_status.upper())
        background_request.status = BackgroundCheckWorkflowStatus.COMPLETED
        background_request.completed_at = now
        background_request.next_poll_at = None
        background_request.last_error_code = None
        background_check_repository.add_result(
            db,
            BackgroundCheckResult(
                request_id=background_request.id,
                result=result_value,
                created_at=now,
                expires_at=now + RESULT_TTL,
            ),
        )

    @staticmethod
    def _mark_failed(
        background_request: BackgroundCheckRequest,
        now: datetime,
        error_code: str,
    ) -> None:
        background_request.status = BackgroundCheckWorkflowStatus.FAILED
        background_request.completed_at = now
        background_request.next_poll_at = None
        background_request.last_error_code = error_code

    @staticmethod
    def _stop_automatic_polling(
        background_request: BackgroundCheckRequest,
        now: datetime,
        error_code: str = "AUTOMATIC_TRACKING_LIMIT",
    ) -> None:
        background_request.automatic_polling_stopped_at = now
        background_request.next_poll_at = None
        background_request.last_error_code = error_code

    @staticmethod
    def _should_stop(
        background_request: BackgroundCheckRequest,
        now: datetime,
    ) -> bool:
        if background_request.get_attempt_count >= MAX_GET_ATTEMPTS:
            return True
        if background_request.tracking_started_at is None:
            return False
        return now >= (
            background_request.tracking_started_at + AUTOMATIC_TRACKING_WINDOW
        )

    @staticmethod
    def _retry_delay(response: BackgroundCheckResponse) -> timedelta:
        if response.status_code == 503:
            if response.retry_after_seconds is not None:
                return timedelta(seconds=response.retry_after_seconds)
            return DEFAULT_503_RETRY_INTERVAL
        return GET_RETRY_INTERVAL

    @staticmethod
    def _error_code(response: BackgroundCheckResponse) -> str:
        if response.status_code is not None:
            return f"HTTP_{response.status_code}"
        return response.error_code or "NETWORK_ERROR"


async def run_background_check_poller(stop_event: asyncio.Event) -> None:
    async with HttpBackgroundCheckClient() as client:
        processor = BackgroundCheckProcessor(client)
        while not stop_event.is_set():
            try:
                await processor.process_due_once()
            except Exception:
                pass
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=1.0)
            except TimeoutError:
                continue
