from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_employee, require_employee
from app.models.employee import Employee
from app.services import auth_service, change_request_service
from app.web import templates


router = APIRouter(prefix="/employees", tags=["employees"])


@router.get("/me")
def my_profile(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_employee: Annotated[Employee, Depends(get_current_employee)],
):
    pending_request = change_request_service.get_pending_request(
        db,
        current_employee.employee_number,
    )
    rejected_request_notice = (
        change_request_service.get_latest_unacknowledged_rejection(
            db,
            current_employee.employee_number,
        )
    )
    return templates.TemplateResponse(
        request=request,
        name="employees/me.html",
        context={
            "employee": current_employee,
            "current_user": current_employee,
            "pending_request": pending_request,
            "rejected_request_notice": rejected_request_notice,
        },
    )


@router.post("/me/change-request-notice/dismiss")
def dismiss_change_request_notice(
    db: Annotated[Session, Depends(get_db)],
    current_employee: Annotated[Employee, Depends(require_employee)],
):
    change_request_service.dismiss_rejected_change_request_notices(
        db,
        current_employee.employee_number,
    )
    return RedirectResponse(url="/employees/me", status_code=303)


@router.get("/me/edit/verify-password")
def profile_edit_password_form(
    request: Request,
    current_employee: Annotated[Employee, Depends(require_employee)],
):
    return templates.TemplateResponse(
        request=request,
        name="employees/verify_password.html",
        context={
            "current_user": current_employee,
            "error": None,
        },
    )


@router.post("/me/edit/verify-password")
def verify_profile_edit_password(
    request: Request,
    password: Annotated[str, Form()],
    db: Annotated[Session, Depends(get_db)],
    current_employee: Annotated[Employee, Depends(require_employee)],
):
    session_id = request.cookies[auth_service.SESSION_COOKIE_NAME]
    if not auth_service.verify_password_for_profile_edit(
        db,
        session_id,
        current_employee,
        password,
    ):
        return templates.TemplateResponse(
            request=request,
            name="employees/verify_password.html",
            context={
                "current_user": current_employee,
                "error": "비밀번호가 올바르지 않습니다.",
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    return RedirectResponse(url="/employees/me/edit", status_code=303)


@router.get("/me/edit")
def profile_edit_form(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_employee: Annotated[Employee, Depends(require_employee)],
):
    session_id = request.cookies[auth_service.SESSION_COOKIE_NAME]
    if not auth_service.has_profile_edit_grant(db, session_id):
        return RedirectResponse(
            url="/employees/me/edit/verify-password",
            status_code=303,
        )
    return templates.TemplateResponse(
        request=request,
        name="employees/edit.html",
        context={
            "current_user": current_employee,
            "employee": current_employee,
            "form_data": {},
            "error": None,
        },
    )


@router.post("/me/edit")
def submit_my_profile_change_request(
    request: Request,
    family_name: Annotated[str, Form()],
    given_name: Annotated[str, Form()],
    db: Annotated[Session, Depends(get_db)],
    current_employee: Annotated[Employee, Depends(require_employee)],
    date_of_birth: Annotated[str, Form()] = "",
):
    session_id = request.cookies[auth_service.SESSION_COOKIE_NAME]
    try:
        change_request_service.submit_change_request(
            db=db,
            employee=current_employee,
            session_id=session_id,
            family_name=family_name,
            given_name=given_name,
            date_of_birth_text=date_of_birth,
        )
    except auth_service.ProfileEditAuthorizationError:
        return RedirectResponse(
            url="/employees/me/edit/verify-password",
            status_code=303,
        )
    except change_request_service.ChangeRequestError as error:
        return templates.TemplateResponse(
            request=request,
            name="employees/edit.html",
            context={
                "current_user": current_employee,
                "employee": current_employee,
                "form_data": {
                    "family_name": family_name,
                    "given_name": given_name,
                    "date_of_birth": date_of_birth,
                },
                "error": str(error),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return RedirectResponse(url="/employees/me", status_code=303)


@router.get("/me/password")
def password_change_form(
    request: Request,
    current_employee: Annotated[Employee, Depends(get_current_employee)],
):
    return templates.TemplateResponse(
        request=request,
        name="employees/change_password.html",
        context={"current_user": current_employee, "error": None},
    )


@router.post("/me/password")
def change_my_password(
    request: Request,
    current_password: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
    new_password_confirmation: Annotated[str, Form()],
    db: Annotated[Session, Depends(get_db)],
    current_employee: Annotated[Employee, Depends(get_current_employee)],
):
    session_id = request.cookies[auth_service.SESSION_COOKIE_NAME]
    try:
        auth_service.change_password(
            db=db,
            employee=current_employee,
            current_session_id=session_id,
            current_password=current_password,
            new_password=new_password,
            new_password_confirmation=new_password_confirmation,
        )
    except auth_service.PasswordChangeError as error:
        return templates.TemplateResponse(
            request=request,
            name="employees/change_password.html",
            context={"current_user": current_employee, "error": str(error)},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return RedirectResponse(url="/employees/me", status_code=303)
