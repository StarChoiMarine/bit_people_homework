import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

import app.models  # noqa: F401 - registers every SQLAlchemy model
from app.core.database import Base, SessionLocal, engine
from app.core.schema_migrations import (
    add_employee_change_request_acknowledgement,
    upgrade_audit_log_actions,
)
from app.core.seed import seed_accounts
from app.routers import admin, auth, employee
from app.services import auth_service
from app.services.background_check_processor import run_background_check_poller
from app.web import templates


@asynccontextmanager
async def lifespan(app: FastAPI):
    del app
    Base.metadata.create_all(bind=engine)
    add_employee_change_request_acknowledgement(engine)
    upgrade_audit_log_actions(engine)
    with SessionLocal() as db:
        seed_accounts(db)

    poller_task = None
    stop_event = asyncio.Event()
    if os.getenv("BACKGROUND_CHECK_POLLER_ENABLED", "true").lower() == "true":
        poller_task = asyncio.create_task(run_background_check_poller(stop_event))

    try:
        yield
    finally:
        if poller_task is not None:
            stop_event.set()
            await poller_task


app = FastAPI(
    title="Bit Computer Employee Portal",
    lifespan=lifespan,
)


@app.exception_handler(auth_service.TerminatedAccountError)
async def terminated_account_handler(request: Request, error: Exception):
    del error
    response = templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": auth_service.TERMINATED_ACCOUNT_MESSAGE},
        status_code=401,
    )
    response.delete_cookie(auth_service.SESSION_COOKIE_NAME, path="/")
    return response


app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(auth.router)
app.include_router(employee.router)
app.include_router(admin.router)
