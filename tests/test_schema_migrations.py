from sqlalchemy import create_engine

from app.core.schema_migrations import (
    add_employee_change_request_acknowledgement,
    upgrade_audit_log_actions,
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

    migration_engine.dispose()
    assert existing_action == "CREATE_EMPLOYEE"
    assert self_service_action_count == 1
    assert dismiss_action_count == 1
    assert background_action_count == 1


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
