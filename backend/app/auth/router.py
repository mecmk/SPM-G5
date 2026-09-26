"""HTTP endpoints for story 1.1 (login / logout) and the `me` lookup used by the RBAC UI (1.2)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.auth import service
from app.auth.deps import CurrentUser
from app.auth.schemas import LoginRequest, UserOut
from app.common.audit import record_audit
from app.config import settings
from app.db import get_db

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_CREDENTIALS_MESSAGE = "Invalid email or password."
# The time left travels in the Retry-After header as seconds, never as a clock time, so the
# sign-in page can count it down without any time zone or calendar being involved (AC6).
LOGIN_LOCKED_MESSAGE = "Too many failed sign-in attempts. Try again later."
RETRY_AFTER_HEADER = "Retry-After"


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=settings.session_cookie_name, path="/")


@router.post("/login", response_model=UserOut)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> UserOut:
    """AC1: valid credentials start a session. AC2: any failure returns the same generic 401.

    AC6: an e-mail locked after repeated failures gets 429, with the seconds left in Retry-After.
    """
    try:
        user = service.authenticate(db, payload.email, payload.password)
    except service.LoginLocked as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=LOGIN_LOCKED_MESSAGE,
            headers={RETRY_AFTER_HEADER: str(exc.seconds_left)},
        ) from None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_CREDENTIALS_MESSAGE
        )
    _, token = service.create_session(db, user, user_agent=request.headers.get("user-agent"))
    record_audit(db, actor=user, action="LOGIN", entity_type="user", entity_id=user.id)
    _set_session_cookie(response, token)
    return UserOut.from_user(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Annotated[Session, Depends(get_db)]) -> None:
    """AC5: the server-side session is revoked, so the cookie cannot be reused."""
    token = request.cookies.get(settings.session_cookie_name)
    user = service.get_session_user(db, token)
    if service.revoke_session(db, token) and user is not None:
        record_audit(db, actor=user, action="LOGOUT", entity_type="user", entity_id=user.id)
    _clear_session_cookie(response)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    """Who am I and what may I do - drives navigation visibility (story 1.2 AC2)."""
    return UserOut.from_user(user)
