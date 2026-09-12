from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import require_admin
from app.models.employee import Employee, EmployeeRole
from app.services import change_request_service, employee_service
from app.web import templates


router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/employees")
def employee_list(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[Employee, Depends(require_admin)],
):
    employees = employee_service.list_employees(db)
    pending_employee_numbers = (
        change_request_service.get_pending_employee_numbers(db)
    )
    return templates.TemplateResponse(
        request=request,
        name="admin/employee_list.html",
        context={
            "employees": employees,
            "pending_employee_numbers": pending_employee_numbers,
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

    change_requests = change_request_service.get_employee_requests(
        db,
        employee_number,
    )
    pending_request = change_request_service.get_pending_request(
        db,
        employee_number,
    )
    return templates.TemplateResponse(
        request=request,
        name="admin/employee_detail.html",
        context={
            "employee": employee,
            "change_requests": change_requests,
            "pending_request": pending_request,
            "current_user": admin,
        },
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
