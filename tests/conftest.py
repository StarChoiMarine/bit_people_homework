import os
import tempfile
from pathlib import Path


TEST_DATABASE_DIRECTORY = tempfile.TemporaryDirectory()
os.environ["DATABASE_PATH"] = str(
    Path(TEST_DATABASE_DIRECTORY.name) / "employee_portal_test.db"
)
os.environ["BACKGROUND_CHECK_POLLER_ENABLED"] = "false"


def pytest_sessionfinish(session, exitstatus) -> None:
    del session, exitstatus

    from app.core.database import engine

    engine.dispose()
    TEST_DATABASE_DIRECTORY.cleanup()
