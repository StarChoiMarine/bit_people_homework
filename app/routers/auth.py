import os
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.employee import EmployeeRole
from app.services import auth_service
from app.web import templates


router = APIRouter()
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"


def _destination_for_role(role: EmployeeRole) -> str:
    if role == EmployeeRole.ADMIN:
        return "/admin/employees"
    return "/employees/me"


@router.get("/")
def home(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    session_id = request.cookies.get(auth_service.SESSION_COOKIE_NAME)
    if session_id is None:
        return RedirectResponse(url="/login", status_code=303)

    employee = auth_service.get_employee_for_session(db, session_id)
    if employee is None:
        response = RedirectResponse(url="/login", status_code=303)
        response.delete_cookie(auth_service.SESSION_COOKIE_NAME, path="/")
        return response
    return RedirectResponse(
        url=_destination_for_role(employee.role),
        status_code=303,
    )


@router.get("/login")
def login_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    session_id = request.cookies.get(auth_service.SESSION_COOKIE_NAME)
    if session_id is not None:
        employee = auth_service.get_employee_for_session(db, session_id)
        if employee is not None:
            return RedirectResponse(
                url=_destination_for_role(employee.role),
                status_code=303,
            )

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": None},
    )


@router.post("/login")
def login(
    request: Request,
    login_id: Annotated[str, Form()],
    password: Annotated[str, Form()],
    db: Annotated[Session, Depends(get_db)],
):
    employee = auth_service.authenticate(db, login_id, password)
    if employee is None:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "아이디 또는 비밀번호를 확인해 주세요."},
            status_code=401,
        )

    previous_session_id = request.cookies.get(auth_service.SESSION_COOKIE_NAME)
    if previous_session_id is not None:
        auth_service.delete_session(db, previous_session_id)

    session_id = auth_service.create_session(db, employee)
    response = RedirectResponse(
        url=_destination_for_role(employee.role),
        status_code=303,
    )
    response.set_cookie(
        key=auth_service.SESSION_COOKIE_NAME,
        value=session_id,
        max_age=int(auth_service.SESSION_LIFETIME.total_seconds()),
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/logout")
def logout(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    session_id = request.cookies.get(auth_service.SESSION_COOKIE_NAME)
    if session_id is not None:
        auth_service.delete_session(db, session_id)

    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(
        key=auth_service.SESSION_COOKIE_NAME,
        path="/",
        secure=COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )
    return response
