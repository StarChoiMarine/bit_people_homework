import os
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import httpx


BACKGROUND_CHECK_API_URL = os.getenv(
    "BACKGROUND_CHECK_API_URL",
    "https://54capvm12g.execute-api.ap-northeast-2.amazonaws.com",
)


@dataclass(frozen=True)
class HistoryCheck:
    check_id: str
    status: str
    created_at: datetime | None


@dataclass(frozen=True)
class BackgroundCheckResponse:
    status_code: int | None
    check_id: str | None = None
    employee_id: str | None = None
    status: str | None = None
    created_at: datetime | None = None
    checks: tuple[HistoryCheck, ...] = ()
    retry_after_seconds: int | None = None
    error_code: str | None = None


class BackgroundCheckClient(Protocol):
    async def create_check(
        self,
        employee_id: str,
        first_name: str,
        last_name: str,
        date_of_birth: str,
    ) -> BackgroundCheckResponse: ...

    async def get_check(self, check_id: str) -> BackgroundCheckResponse: ...

    async def list_checks(self, employee_id: str) -> BackgroundCheckResponse: ...


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    except ValueError:
        return None


def _positive_integer(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


class HttpBackgroundCheckClient:
    def __init__(
        self,
        base_url: str = BACKGROUND_CHECK_API_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            transport=transport,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        del exc_type, exc_value, traceback
        await self._client.aclose()

    async def create_check(
        self,
        employee_id: str,
        first_name: str,
        last_name: str,
        date_of_birth: str,
    ) -> BackgroundCheckResponse:
        try:
            response = await self._client.post(
                "/background-checks",
                json={
                    "employeeId": employee_id,
                    "firstName": first_name,
                    "lastName": last_name,
                    "dateOfBirth": date_of_birth,
                },
                timeout=5.0,
            )
        except httpx.TimeoutException:
            return BackgroundCheckResponse(None, error_code="TIMEOUT")
        except httpx.RequestError:
            return BackgroundCheckResponse(None, error_code="NETWORK_ERROR")
        return self._parse_single_response(response)

    async def get_check(self, check_id: str) -> BackgroundCheckResponse:
        try:
            response = await self._client.get(
                f"/background-checks/{check_id}",
                timeout=35.0,
            )
        except httpx.TimeoutException:
            return BackgroundCheckResponse(None, error_code="TIMEOUT")
        except httpx.RequestError:
            return BackgroundCheckResponse(None, error_code="NETWORK_ERROR")
        return self._parse_single_response(response)

    async def list_checks(self, employee_id: str) -> BackgroundCheckResponse:
        try:
            response = await self._client.get(
                "/background-checks",
                params={"employeeId": employee_id},
                timeout=35.0,
            )
        except httpx.TimeoutException:
            return BackgroundCheckResponse(None, error_code="TIMEOUT")
        except httpx.RequestError:
            return BackgroundCheckResponse(None, error_code="NETWORK_ERROR")

        data = self._safe_json(response)
        checks = []
        for item in data.get("checks", []):
            if not isinstance(item, dict):
                continue
            check_id = item.get("checkId")
            status = item.get("status")
            if isinstance(check_id, str) and isinstance(status, str):
                checks.append(
                    HistoryCheck(
                        check_id=check_id,
                        status=status,
                        created_at=_parse_datetime(item.get("createdAt")),
                    )
                )
        return BackgroundCheckResponse(
            status_code=response.status_code,
            employee_id=(
                data.get("employeeId")
                if isinstance(data.get("employeeId"), str)
                else None
            ),
            checks=tuple(checks),
            retry_after_seconds=self._retry_after(response, data),
        )

    def _parse_single_response(
        self,
        response: httpx.Response,
    ) -> BackgroundCheckResponse:
        data = self._safe_json(response)
        return BackgroundCheckResponse(
            status_code=response.status_code,
            check_id=(data.get("checkId") if isinstance(data.get("checkId"), str) else None),
            employee_id=(
                data.get("employeeId")
                if isinstance(data.get("employeeId"), str)
                else None
            ),
            status=(data.get("status") if isinstance(data.get("status"), str) else None),
            created_at=_parse_datetime(data.get("createdAt")),
            retry_after_seconds=self._retry_after(response, data),
        )

    @staticmethod
    def _safe_json(response: httpx.Response) -> dict[str, object]:
        try:
            data = response.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _retry_after(
        response: httpx.Response,
        data: dict[str, object],
    ) -> int | None:
        header_value = _positive_integer(response.headers.get("Retry-After"))
        if header_value is not None:
            return header_value
        return _positive_integer(data.get("retryAfter"))
