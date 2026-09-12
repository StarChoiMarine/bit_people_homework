from sqlalchemy import Engine


AUDIT_ACTIONS = (
    "CREATE_EMPLOYEE",
    "TERMINATE_EMPLOYEE",
    "REQUEST_PROFILE_CHANGE",
    "APPROVE_PROFILE_CHANGE",
    "REJECT_PROFILE_CHANGE",
    "DISMISS_PROFILE_CHANGE_NOTICE",
    "CHANGE_PASSWORD",
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
                        action VARCHAR(30) NOT NULL,
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
