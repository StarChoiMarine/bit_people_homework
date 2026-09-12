from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LoginSession(Base):
    __tablename__ = "auth_sessions"

    session_id_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    employee_number: Mapped[str] = mapped_column(
        ForeignKey("employees.employee_number", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
