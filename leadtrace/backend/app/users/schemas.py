from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.users.models import User, UserRole


class UserResponse(BaseModel):
    id: UUID
    username: str
    display_name: str
    role: UserRole
    is_enabled: bool
    must_change_password: bool

    @classmethod
    def from_user(cls, user: User) -> "UserResponse":
        return cls(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            is_enabled=user.is_enabled,
            must_change_password=user.must_change_password,
        )


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    display_name: str = Field(min_length=1, max_length=120)
    role: UserRole
    initial_password: str = Field(min_length=1, max_length=1024)


class PasswordResetRequest(BaseModel):
    one_time_password: str = Field(min_length=1, max_length=1024)


class EnabledUpdateRequest(BaseModel):
    is_enabled: bool


class RoleUpdateRequest(BaseModel):
    role: UserRole

