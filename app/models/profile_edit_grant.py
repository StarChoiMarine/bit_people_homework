from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ProfileEditGrant(Base):
    __tablename__ = "profile_edit_grants"

    session_id_hash: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("auth_sessions.session_id_hash", ondelete="CASCADE"),
        primary_key=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

