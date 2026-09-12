from sqlalchemy import Engine


AUDIT_ACTIONS = (
    "CREATE_EMPLOYEE",
    "UPDATE_EMPLOYEE",
    "TERMINATE_EMPLOYEE",
    "REQUEST_PROFILE_CHANGE",
    "APPROVE_PROFILE_CHANGE",
    "REJECT_PROFILE_CHANGE",
    "DISMISS_PROFILE_CHANGE_NOTICE",
    "CHANGE_PASSWORD",
    "REQUEST_BACKGROUND_CHECK",
    "VIEW_BACKGROUND_CHECK_RESULT",
    "ACKNOWLEDGE_BACKGROUND_CHECK_RESULT",
)


def upgrade_audit_log_actions(engine: Engine) -> None:
    with engine.connect() as connection:
        table_sql = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'audit_logs'"
        ).scalar_one_or_none()
        connection.commit()

        if table_sql is None or all(action in table_sql for action in AUDIT_ACTIONS):
            return

        allowed_actions = ", ".join(f"'{action}'" for action in AUDIT_ACTIONS)
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        try:
            with connection.begin():
                connection.exec_driver_sql(
                    f"""
                    CREATE TABLE audit_logs_new (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        action VARCHAR(40) NOT NULL,
                        actor_employee_number VARCHAR(20) NOT NULL,
                        target_employee_number VARCHAR(20) NOT NULL,
                        created_at DATETIME NOT NULL,
                        details JSON,
                        CONSTRAINT audit_action CHECK (action IN ({allowed_actions})),
                        FOREIGN KEY(actor_employee_number)
                            REFERENCES employees (employee_number) ON DELETE RESTRICT,
                        FOREIGN KEY(target_employee_number)
                            REFERENCES employees (employee_number) ON DELETE RESTRICT
                    )
                    """
                )
                connection.exec_driver_sql(
                    "INSERT INTO audit_logs_new "
                    "SELECT id, action, actor_employee_number, "
                    "target_employee_number, created_at, details FROM audit_logs"
                )
                connection.exec_driver_sql("DROP TABLE audit_logs")
                connection.exec_driver_sql(
                    "ALTER TABLE audit_logs_new RENAME TO audit_logs"
                )
                connection.exec_driver_sql(
                    "CREATE INDEX ix_audit_logs_actor_employee_number "
                    "ON audit_logs (actor_employee_number)"
                )
                connection.exec_driver_sql(
                    "CREATE INDEX ix_audit_logs_target_employee_number "
                    "ON audit_logs (target_employee_number)"
                )
                connection.exec_driver_sql(
                    "CREATE INDEX ix_audit_logs_created_at "
                    "ON audit_logs (created_at)"
                )
        finally:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()


def add_employee_change_request_acknowledgement(engine: Engine) -> None:
    with engine.begin() as connection:
        table_exists = connection.exec_driver_sql(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'employee_change_requests'"
        ).scalar_one_or_none()
        if table_exists is None:
            return

        columns = connection.exec_driver_sql(
            "PRAGMA table_info(employee_change_requests)"
        ).mappings()
        column_names = {column["name"] for column in columns}
        if "employee_acknowledged_at" not in column_names:
            connection.exec_driver_sql(
                "ALTER TABLE employee_change_requests "
                "ADD COLUMN employee_acknowledged_at DATETIME"
            )


def upgrade_background_check_request_snapshots(engine: Engine) -> None:
    with engine.begin() as connection:
        table_exists = connection.exec_driver_sql(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'background_check_requests'"
        ).scalar_one_or_none()
        if table_exists is None:
            return

        columns = connection.exec_driver_sql(
            "PRAGMA table_info(background_check_requests)"
        ).mappings()
        column_names = {column["name"] for column in columns}

        snapshot_columns = {
            "submitted_full_name": "VARCHAR(100) NOT NULL DEFAULT ''",
            "submitted_family_name": "VARCHAR(50) NOT NULL DEFAULT ''",
            "submitted_given_name": "VARCHAR(50) NOT NULL DEFAULT ''",
            "submitted_date_of_birth": (
                "DATE NOT NULL DEFAULT '1900-01-01'"
            ),
        }
        for column_name, column_definition in snapshot_columns.items():
            if column_name not in column_names:
                connection.exec_driver_sql(
                    "ALTER TABLE background_check_requests "
                    f"ADD COLUMN {column_name} {column_definition}"
                )

        connection.exec_driver_sql(
            "UPDATE background_check_requests "
            "SET submitted_full_name = ("
            "        SELECT family_name || given_name FROM employees "
            "        WHERE employees.employee_number = "
            "              background_check_requests.employee_number"
            "    ), "
            "    submitted_family_name = ("
            "        SELECT family_name FROM employees "
            "        WHERE employees.employee_number = "
            "              background_check_requests.employee_number"
            "    ), "
            "    submitted_given_name = ("
            "        SELECT given_name FROM employees "
            "        WHERE employees.employee_number = "
            "              background_check_requests.employee_number"
            "    ), "
            "    submitted_date_of_birth = ("
            "        SELECT date_of_birth FROM employees "
            "        WHERE employees.employee_number = "
            "              background_check_requests.employee_number"
            "    ) "
            "WHERE submitted_full_name = ''"
        )

        connection.exec_driver_sql(
            "DROP INDEX IF EXISTS uq_open_background_check_per_employee"
        )
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX uq_open_background_check_per_employee "
            "ON background_check_requests (employee_number) "
            "WHERE status IN ('REQUESTED', 'SUBMISSION_UNKNOWN', 'PENDING') "
            "OR (status = 'COMPLETED' AND result_deleted_at IS NULL)"
        )
