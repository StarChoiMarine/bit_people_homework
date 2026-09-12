import json
import os
import tempfile
from pathlib import Path


TEST_DATABASE_DIRECTORY = tempfile.TemporaryDirectory()
os.environ["DATABASE_PATH"] = str(
    Path(TEST_DATABASE_DIRECTORY.name) / "employee_portal_test.db"
)
TEST_CREDENTIALS_PATH = Path(TEST_DATABASE_DIRECTORY.name) / "test_credentials.json"
TEST_CREDENTIALS_PATH.write_text(
    json.dumps(
        {
            "admin": "TestAdmin-Password-2026!",
            "emp001": "TestEmployee001-Password!",
            "emp002": "TestEmployee002-Password!",
            "emp003": "TestEmployee003-Password!",
            "emp004": "TestEmployee004-Password!",
            "emp005": "TestEmployee005-Password!",
            "emp006": "TestEmployee006-Password!",
            "emp007": "TestEmployee007-Password!",
            "emp008": "TestEmployee008-Password!",
            "emp009": "TestEmployee009-Password!",
            "emp010": "TestEmployee010-Password!",
        }
    ),
    encoding="utf-8",
)
os.environ["SEED_CREDENTIALS_FILE"] = str(TEST_CREDENTIALS_PATH)
os.environ["BACKGROUND_CHECK_POLLER_ENABLED"] = "false"


def pytest_sessionfinish(session, exitstatus) -> None:
    del session, exitstatus

    from app.core.database import engine

    engine.dispose()
    TEST_DATABASE_DIRECTORY.cleanup()
