from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.dependencies import get_current_employee
from app.models.employee import Employee
from app.web import templates


router = APIRouter(prefix="/employees", tags=["employees"])


@router.get("/me")
def my_profile(
    request: Request,
    current_employee: Annotated[Employee, Depends(get_current_employee)],
):
    return templates.TemplateResponse(
        request=request,
        name="employees/me.html",
        context={
            "employee": current_employee,
            "current_user": current_employee,
        },
    )

