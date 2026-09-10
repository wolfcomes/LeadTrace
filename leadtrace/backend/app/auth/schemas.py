from __future__ import annotations

from pydantic import BaseModel, Field

from app.users.models import User, UserRole


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=1024)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class ReauthenticationRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class AuthenticatedUser(BaseModel):
    username: str
    display_name: str
    role: UserRole
    must_change_password: bool

    @classmethod
    def from_user(cls, user: User) -> "AuthenticatedUser":
        return cls(
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            must_change_password=user.must_change_password,
        )


class AuthenticationResponse(BaseModel):
    user: AuthenticatedUser
    csrf_token: str
