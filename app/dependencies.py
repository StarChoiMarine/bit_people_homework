from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.employee import Employee, EmployeeRole
from app.services import auth_service


def get_current_employee(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> Employee:
    session_id = request.cookies.get(auth_service.SESSION_COOKIE_NAME)
    if session_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인이 필요합니다.",
        )

    employee = auth_service.get_employee_for_session(db, session_id)
    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="세션이 유효하지 않습니다.",
        )
    return employee


def require_admin(
    current_employee: Annotated[Employee, Depends(get_current_employee)],
) -> Employee:
    if current_employee.role != EmployeeRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다.",
        )
    return current_employee

