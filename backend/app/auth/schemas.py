from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.auth.models import User
from app.auth.permissions import permissions_for


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1)


class UserOut(BaseModel):
    """The signed-in user as seen by the frontend, including the permissions the UI may show."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role_code: str
    role_name: str
    is_internal: bool
    organisation_id: uuid.UUID | None
    organisation_name: str | None
    permissions: list[str]

    @classmethod
    def from_user(cls, user: User) -> UserOut:
        return cls(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role_code=user.role_code,
            role_name=user.role.name,
            is_internal=user.role.is_internal,
            organisation_id=user.organisation_id,
            organisation_name=user.organisation.name if user.organisation else None,
            permissions=sorted(permissions_for(user.role_code)),
        )
