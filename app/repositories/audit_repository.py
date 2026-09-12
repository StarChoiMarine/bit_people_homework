from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def add(db: Session, audit_log: AuditLog) -> None:
    db.add(audit_log)

