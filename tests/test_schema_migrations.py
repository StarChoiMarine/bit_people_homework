from sqlalchemy import create_engine

from app.core.schema_migrations import (
    add_employee_change_request_acknowledgement,
    upgrade_audit_log_actions,
    upgrade_background_check_request_snapshots,
)


def test_legacy_audit_actions_are_upgraded_without_data_loss(tmp_path) -> None:
    database_path = tmp_path / "legacy.db"
    migration_engine = create_engine(f"sqlite:///{database_path}")

    with migration_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE employees (employee_number VARCHAR(20) PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            "INSERT INTO employees (employee_number) "
            "VALUES ('ADM-001'), ('EMP-001')"
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE audit_logs (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                action VARCHAR(18) NOT NULL,
                actor_employee_number VARCHAR(20) NOT NULL,
                target_employee_number VARCHAR(20) NOT NULL,
                created_at DATETIME NOT NULL,
                details JSON,
                CONSTRAINT audit_action CHECK (
                    action IN ('CREATE_EMPLOYEE', 'TERMINATE_EMPLOYEE')
                )
            )
            """
        )
        connection.exec_driver_sql(
            "INSERT INTO audit_logs "
            "(action, actor_employee_number, target_employee_number, created_at) "
            "VALUES ('CREATE_EMPLOYEE', 'ADM-001', 'EMP-001', '2026-09-12')"
        )

    upgrade_audit_log_actions(migration_engine)

    with migration_engine.begin() as connection:
        existing_action = connection.exec_driver_sql(
            "SELECT action FROM audit_logs WHERE id = 1"
        ).scalar_one()
        self_service_action_count = connection.exec_driver_sql(
            "INSERT INTO audit_logs "
            "(action, actor_employee_number, target_employee_number, created_at) "
            "VALUES ('REQUEST_PROFILE_CHANGE', 'EMP-001', 'EMP-001', '2026-09-12')"
        ).rowcount
        dismiss_action_count = connection.exec_driver_sql(
            "INSERT INTO audit_logs "
            "(action, actor_employee_number, target_employee_number, created_at) "
            "VALUES ('DISMISS_PROFILE_CHANGE_NOTICE', 'EMP-001', "
            "'EMP-001', '2026-09-12')"
        ).rowcount
        background_action_count = connection.exec_driver_sql(
            "INSERT INTO audit_logs "
            "(action, actor_employee_number, target_employee_number, created_at) "
            "VALUES ('ACKNOWLEDGE_BACKGROUND_CHECK_RESULT', 'ADM-001', "
            "'EMP-001', '2026-09-12')"
        ).rowcount
        update_action_count = connection.exec_driver_sql(
            "INSERT INTO audit_logs "
            "(action, actor_employee_number, target_employee_number, created_at) "
            "VALUES ('UPDATE_EMPLOYEE', 'ADM-001', 'EMP-001', '2026-09-12')"
        ).rowcount

    migration_engine.dispose()
    assert existing_action == "CREATE_EMPLOYEE"
    assert self_service_action_count == 1
    assert dismiss_action_count == 1
    assert background_action_count == 1
    assert update_action_count == 1


def test_acknowledgement_column_is_added_to_existing_change_request_table(
    tmp_path,
) -> None:
    database_path = tmp_path / "legacy_change_requests.db"
    migration_engine = create_engine(f"sqlite:///{database_path}")

    with migration_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE employee_change_requests (id INTEGER PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            "INSERT INTO employee_change_requests (id) VALUES (1)"
        )

    add_employee_change_request_acknowledgement(migration_engine)
    add_employee_change_request_acknowledgement(migration_engine)

    with migration_engine.begin() as connection:
        columns = connection.exec_driver_sql(
            "PRAGMA table_info(employee_change_requests)"
        ).mappings()
        column_names = {column["name"] for column in columns}
        preserved_id = connection.exec_driver_sql(
            "SELECT id FROM employee_change_requests"
        ).scalar_one()

    migration_engine.dispose()
    assert "employee_acknowledged_at" in column_names
    assert preserved_id == 1


def test_background_check_snapshots_and_blocking_index_are_upgraded(
    tmp_path,
) -> None:
    database_path = tmp_path / "legacy_background_check.db"
    migration_engine = create_engine(f"sqlite:///{database_path}")

    with migration_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE employees ("
            "employee_number VARCHAR(20) PRIMARY KEY, "
            "family_name VARCHAR(50) NOT NULL, "
            "given_name VARCHAR(50) NOT NULL, "
            "date_of_birth DATE)"
        )
        connection.exec_driver_sql(
            "INSERT INTO employees VALUES "
            "('EMP-003', '남궁', '서준', '1988-07-21')"
        )
        connection.exec_driver_sql(
            "CREATE TABLE background_check_requests ("
            "id INTEGER PRIMARY KEY, "
            "employee_number VARCHAR(20) NOT NULL, "
            "status VARCHAR(30) NOT NULL, "
            "result_deleted_at DATETIME)"
        )
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX uq_open_background_check_per_employee "
            "ON background_check_requests (employee_number) "
            "WHERE status IN ('REQUESTED', 'SUBMISSION_UNKNOWN', 'PENDING')"
        )
        connection.exec_driver_sql(
            "INSERT INTO background_check_requests "
            "VALUES (1, 'EMP-003', 'COMPLETED', NULL)"
        )

    upgrade_background_check_request_snapshots(migration_engine)
    upgrade_background_check_request_snapshots(migration_engine)

    with migration_engine.begin() as connection:
        columns = connection.exec_driver_sql(
            "PRAGMA table_info(background_check_requests)"
        ).mappings()
        column_names = {column["name"] for column in columns}
        snapshot = connection.exec_driver_sql(
            "SELECT submitted_full_name, submitted_family_name, "
            "submitted_given_name, submitted_date_of_birth "
            "FROM background_check_requests WHERE id = 1"
        ).one()
        index_sql = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'index' "
            "AND name = 'uq_open_background_check_per_employee'"
        ).scalar_one()

    migration_engine.dispose()
    assert {
        "submitted_full_name",
        "submitted_family_name",
        "submitted_given_name",
        "submitted_date_of_birth",
    }.issubset(column_names)
    assert tuple(snapshot) == ("남궁서준", "남궁", "서준", "1988-07-21")
    assert "status = 'COMPLETED' AND result_deleted_at IS NULL" in index_sql
