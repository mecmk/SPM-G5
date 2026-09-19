"""FastAPI dependencies for authentication (1.1) and authorisation (1.2).

    from app.auth.deps import CurrentUser, require_permission

    @router.get("/things")
    def list_things(user: CurrentUser): ...                      # any signed-in user

    @router.post("/things", dependencies=[Depends(require_permission(Permission.THINGS_MANAGE))])
    def create_thing(user: CurrentUser): ...                     # role must hold the permission

Unauthenticated -> 401. Authenticated but not permitted -> 403 (story 1.2 AC4: direct API
requests outside the role's permitted set are rejected).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth import service
from app.auth.models import User
from app.auth.permissions import Permission, role_has
from app.config import settings
from app.db import get_db


def get_current_user(request: Request, db: Annotated[Session, Depends(get_db)]) -> User:
    token = request.cookies.get(settings.session_cookie_name)
    user = service.get_session_user(db, token)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_permission(*required: Permission):
    """Build a dependency that admits only users whose role holds every ``required`` permission."""

    def dependency(user: CurrentUser) -> User:
        if not role_has(user.role_code, *required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your role does not permit this action.",
            )
        return user

    return dependency
