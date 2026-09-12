from sqlalchemy.orm import Session

from app.models.profile_edit_grant import ProfileEditGrant


def get_by_session_hash(
    db: Session,
    session_id_hash: str,
) -> ProfileEditGrant | None:
    return db.get(ProfileEditGrant, session_id_hash)


def add(db: Session, grant: ProfileEditGrant) -> None:
    db.add(grant)


def delete(db: Session, grant: ProfileEditGrant) -> None:
    db.delete(grant)

