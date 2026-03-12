"""Gallery visibility filter helpers (prep for access control)."""
from sqlalchemy import or_, true
from db.models import Gallery


def gallery_visibility_filter(user_id: int, role: str):
    """Returns SQLAlchemy WHERE clause for gallery visibility."""
    if role == "admin":
        return true()
    return or_(
        Gallery.visibility == "public",
        Gallery.created_by_user_id == user_id,
    )
