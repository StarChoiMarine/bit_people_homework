from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import require_admin
from app.models.employee import Employee, EmployeeRole
from app.services import (
    auth_service,
    background_check_service,
    change_request_service,
    employee_service,
)
from app.web import templates


router = APIRouter(prefix="/admin", tags=["admin"])


def _employee_detail_response(
    request: Request,
    db: Session,
    admin: Employee,
    employee: Employee,
    background_error: str | None = None,
    background_request_reason: str = "",
    status_code: int = status.HTTP_200_OK,
):
    change_requests = change_request_service.get_employee_requests(
        db,
        employee.employee_number,
    )
    pending_request = change_request_service.get_pending_request(
        db,
        employee.employee_number,
    )
    background_requests, background_result_request_ids = (
        background_check_service.list_employee_requests(
            db,
            employee.employee_number,
        )
    )
    open_background_request = next(
        (
            item
            for item in background_requests
            if item.status.value
            in {"REQUESTED", "SUBMISSION_UNKNOWN", "PENDING"}
        ),
        None,
    )
    unacknowledged_background_request = next(
        (
            item
            for item in background_requests
            if item.status.value == "COMPLETED"
            and item.id in background_result_request_ids
        ),
        None,
    )
    return templates.TemplateResponse(
        request=request,
        name="admin/employee_detail.html",
        context={
            "employee": employee,
            "change_requests": change_requests,
            "pending_request": pending_request,
            "background_requests": background_requests,
            "background_result_request_ids": background_result_request_ids,
            "open_background_request": open_background_request,
            "unacknowledged_background_request": (
                unacknowledged_background_request
            ),
            "background_error": background_error,
            "background_request_reason": background_request_reason,
            "current_user": admin,
        },
        status_code=status_code,
    )


@router.get("/employees")
def employee_list(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[Employee, Depends(require_admin)],
):
    pending_employee_numbers = (
        change_request_service.get_pending_employee_numbers(db)
    )
    background_attention_employee_numbers = (
        background_check_service.get_employee_numbers_requiring_attention(db)
    )
    attention_employee_numbers = (
        pending_employee_numbers | background_attention_employee_numbers
    )
    employees = employee_service.list_employees(db)
    return templates.TemplateResponse(
        request=request,
        name="admin/employee_list.html",
        context={
            "employees": employees,
            "attention_employee_numbers": attention_employee_numbers,
            "current_user": admin,
        },
    )


@router.get("/employees/new")
def new_employee_form(
    request: Request,
    admin: Annotated[Employee, Depends(require_admin)],
):
    return templates.TemplateResponse(
        request=request,
        name="admin/employee_form.html",
        context={
            "current_user": admin,
            "roles": list(EmployeeRole),
            "form_data": {},
            "error": None,
        },
    )


@router.post("/employees/new")
def create_employee(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[Employee, Depends(require_admin)],
    employee_number: Annotated[str, Form()],
    login_id: Annotated[str, Form()],
    family_name: Annotated[str, Form()],
    given_name: Annotated[str, Form()],
    role: Annotated[str, Form()],
    password: Annotated[str, Form()],
    date_of_birth: Annotated[str, Form()] = "",
):
    form_data = {
        "employee_number": employee_number,
        "login_id": login_id,
        "full_name": f"{family_name.strip()}{given_name.strip()}",
        "family_name": family_name,
        "given_name": given_name,
        "date_of_birth": date_of_birth,
        "role": role,
    }

    try:
        employee = employee_service.create_employee(
            db=db,
            employee_number=employee_number,
            login_id=login_id,
            family_name=family_name,
            given_name=given_name,
            date_of_birth_text=date_of_birth,
            role_text=role,
            password=password,
            actor_employee_number=admin.employee_number,
        )
    except employee_service.EmployeeCreationError as error:
        return templates.TemplateResponse(
            request=request,
            name="admin/employee_form.html",
            context={
                "current_user": admin,
                "roles": list(EmployeeRole),
                "form_data": form_data,
                "error": str(error),
            },
            status_code=status.HTTP_409_CONFLICT,
        )

    return RedirectResponse(
        url=f"/admin/employees/{employee.employee_number}",
        status_code=303,
    )


def _get_editable_employee(
    db: Session,
    employee_number: str,
    admin: Employee,
) -> Employee:
    employee = employee_service.get_employee_detail(db, employee_number)
    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="직원을 찾을 수 없습니다.",
        )
    if employee.employee_number == admin.employee_number:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "관리자 자신의 정보는 정보 변경 요청을 통해 "
                "다른 관리자의 승인을 받아야 합니다."
            ),
        )
    return employee


@router.get("/employees/{employee_number}/edit/verify-password")
def employee_edit_password_form(
    employee_number: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[Employee, Depends(require_admin)],
):
    employee = _get_editable_employee(db, employee_number, admin)
    return templates.TemplateResponse(
        request=request,
        name="admin/employee_edit_verify_password.html",
        context={
            "current_user": admin,
            "employee": employee,
            "error": None,
        },
    )


@router.post("/employees/{employee_number}/edit/verify-password")
def verify_employee_edit_password(
    employee_number: str,
    request: Request,
    password: Annotated[str, Form()],
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[Employee, Depends(require_admin)],
):
    employee = _get_editable_employee(db, employee_number, admin)
    session_id = request.cookies[auth_service.SESSION_COOKIE_NAME]
    if not auth_service.verify_password_for_profile_edit(
        db,
        session_id,
        admin,
        password,
    ):
        return templates.TemplateResponse(
            request=request,
            name="admin/employee_edit_verify_password.html",
            context={
                "current_user": admin,
                "employee": employee,
                "error": "비밀번호가 올바르지 않습니다.",
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    return RedirectResponse(
        url=f"/admin/employees/{employee_number}/edit",
        status_code=303,
    )


@router.get("/employees/{employee_number}/edit")
def employee_edit_form(
    employee_number: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[Employee, Depends(require_admin)],
):
    employee = _get_editable_employee(db, employee_number, admin)
    session_id = request.cookies[auth_service.SESSION_COOKIE_NAME]
    if not auth_service.has_profile_edit_grant(db, session_id):
        return RedirectResponse(
            url=f"/admin/employees/{employee_number}/edit/verify-password",
            status_code=303,
        )
    return templates.TemplateResponse(
        request=request,
        name="admin/employee_edit.html",
        context={
            "current_user": admin,
            "employee": employee,
            "roles": list(EmployeeRole),
            "form_data": {},
            "error": None,
        },
    )


@router.post("/employees/{employee_number}/edit")
def update_employee(
    employee_number: str,
    request: Request,
    login_id: Annotated[str, Form()],
    family_name: Annotated[str, Form()],
    given_name: Annotated[str, Form()],
    role: Annotated[str, Form()],
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[Employee, Depends(require_admin)],
    date_of_birth: Annotated[str, Form()] = "",
    new_password: Annotated[str, Form()] = "",
):
    employee = _get_editable_employee(db, employee_number, admin)
    session_id = request.cookies[auth_service.SESSION_COOKIE_NAME]
    form_data = {
        "login_id": login_id,
        "family_name": family_name,
        "given_name": given_name,
        "full_name": f"{family_name.strip()}{given_name.strip()}",
        "date_of_birth": date_of_birth,
        "role": role,
    }
    try:
        updated_employee = employee_service.update_employee_by_admin(
            db=db,
            employee_number=employee_number,
            actor_employee_number=admin.employee_number,
            session_id=session_id,
            login_id=login_id,
            family_name=family_name,
            given_name=given_name,
            date_of_birth_text=date_of_birth,
            role_text=role,
            new_password=new_password,
        )
    except auth_service.ProfileEditAuthorizationError:
        return RedirectResponse(
            url=f"/admin/employees/{employee_number}/edit/verify-password",
            status_code=303,
        )
    except employee_service.SelfAdminEditError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(error),
        ) from error
    except employee_service.EmployeeUpdateError as error:
        return templates.TemplateResponse(
            request=request,
            name="admin/employee_edit.html",
            context={
                "current_user": admin,
                "employee": employee,
                "roles": list(EmployeeRole),
                "form_data": form_data,
                "error": str(error),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if updated_employee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="직원을 찾을 수 없습니다.",
        )
    return RedirectResponse(
        url=f"/admin/employees/{updated_employee.employee_number}",
        status_code=303,
    )


@router.get("/employees/{employee_number}")
def employee_detail(
    employee_number: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[Employee, Depends(require_admin)],
):
    employee = employee_service.get_employee_detail(db, employee_number)
    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="직원을 찾을 수 없습니다.",
        )

    return _employee_detail_response(request, db, admin, employee)


@router.post("/employees/{employee_number}/background-checks")
def request_background_check(
    employee_number: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[Employee, Depends(require_admin)],
    request_reason: Annotated[str, Form()] = "",
):
    employee = employee_service.get_employee_detail(db, employee_number)
    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="직원을 찾을 수 없습니다.",
        )
    try:
        background_check_service.create_request(
            db=db,
            employee_number=employee_number,
            requested_by_employee_number=admin.employee_number,
            request_reason=request_reason,
        )
    except background_check_service.BackgroundCheckAlreadyOpenError as error:
        return _employee_detail_response(
            request,
            db,
            admin,
            employee,
            background_error=str(error),
            background_request_reason=request_reason,
            status_code=status.HTTP_409_CONFLICT,
        )
    except background_check_service.BackgroundCheckError as error:
        return _employee_detail_response(
            request,
            db,
            admin,
            employee,
            background_error=str(error),
            background_request_reason=request_reason,
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return RedirectResponse(
        url=f"/admin/employees/{employee_number}",
        status_code=303,
    )


@router.post("/background-check-requests/{request_id}/view")
def view_background_check_result(
    request_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[Employee, Depends(require_admin)],
    access_reason: Annotated[str, Form()] = "",
):
    background_request = background_check_service.get_request(db, request_id)
    if background_request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Background Check 요청을 찾을 수 없습니다.",
        )
    employee = employee_service.get_employee_detail(
        db,
        background_request.employee_number,
    )
    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="직원을 찾을 수 없습니다.",
        )
    try:
        result_view = background_check_service.view_result(
            db=db,
            request_id=request_id,
            admin=admin,
            access_reason=access_reason,
        )
    except background_check_service.BackgroundCheckResultUnavailableError as error:
        return _employee_detail_response(
            request,
            db,
            admin,
            employee,
            background_error=str(error),
            status_code=status.HTTP_410_GONE,
        )
    except background_check_service.BackgroundCheckError as error:
        return _employee_detail_response(
            request,
            db,
            admin,
            employee,
            background_error=str(error),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    response = templates.TemplateResponse(
        request=request,
        name="admin/background_check_result.html",
        context={
            "current_user": admin,
            "employee": employee,
            "result_view": result_view,
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/background-check-requests/{request_id}/status")
def background_check_status(
    request_id: int,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[Employee, Depends(require_admin)],
):
    del admin
    try:
        status_view = background_check_service.get_status(db, request_id)
    except background_check_service.BackgroundCheckNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    return JSONResponse(
        content={
            "status": status_view.status.value,
            "is_final": status_view.is_final,
            "result_available": status_view.result_available,
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post("/background-check-requests/{request_id}/acknowledge")
def acknowledge_background_check_result(
    request_id: int,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[Employee, Depends(require_admin)],
):
    try:
        background_request = background_check_service.acknowledge_result(
            db=db,
            request_id=request_id,
            admin=admin,
        )
    except background_check_service.BackgroundCheckNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except background_check_service.BackgroundCheckResultUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=str(error),
        ) from error
    return RedirectResponse(
        url=f"/admin/employees/{background_request.employee_number}",
        status_code=303,
    )


@router.post("/background-check-requests/{request_id}/refresh")
def refresh_background_check_status(
    request_id: int,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[Employee, Depends(require_admin)],
):
    del admin
    try:
        background_request = background_check_service.resume_safe_lookup(
            db,
            request_id,
        )
    except background_check_service.BackgroundCheckNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except background_check_service.BackgroundCheckNotAllowedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    return RedirectResponse(
        url=f"/admin/employees/{background_request.employee_number}",
        status_code=303,
    )


@router.post("/employees/{employee_number}/terminate")
def terminate_employee(
    employee_number: str,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[Employee, Depends(require_admin)],
):
    try:
        employee = employee_service.terminate_employee(
            db,
            employee_number,
            actor_employee_number=admin.employee_number,
        )
    except employee_service.SelfTerminationError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(error),
        ) from error
    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="직원을 찾을 수 없습니다.",
        )
    return RedirectResponse(
        url=f"/admin/employees/{employee.employee_number}",
        status_code=303,
    )


def _review_change_request(
    db: Session,
    request_id: int,
    admin: Employee,
    approve: bool,
):
    try:
        if approve:
            change_request = change_request_service.approve_change_request(
                db,
                request_id,
                reviewer_employee_number=admin.employee_number,
            )
        else:
            change_request = change_request_service.reject_change_request(
                db,
                request_id,
                reviewer_employee_number=admin.employee_number,
            )
    except change_request_service.SelfReviewError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(error),
        ) from error
    except change_request_service.ChangeRequestError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error

    if change_request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="정보 변경 요청을 찾을 수 없습니다.",
        )
    return RedirectResponse(
        url=f"/admin/employees/{change_request.employee_number}",
        status_code=303,
    )


@router.post("/change-requests/{request_id}/approve")
def approve_change_request(
    request_id: int,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[Employee, Depends(require_admin)],
):
    return _review_change_request(db, request_id, admin, approve=True)


@router.post("/change-requests/{request_id}/reject")
def reject_change_request(
    request_id: int,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[Employee, Depends(require_admin)],
):
    return _review_change_request(db, request_id, admin, approve=False)
