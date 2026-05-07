from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SignupRequest(StrictBaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)
    name: str = Field(..., min_length=1, max_length=120)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_input(cls, value: object) -> str:
        email = str(value).strip().lower()
        if not email:
            raise ValueError("Email is required.")
        return email

    @field_validator("password")
    @classmethod
    def validate_password_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Password must not be empty.")
        return value

    @field_validator("name")
    @classmethod
    def normalize_name_input(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("Name is required.")
        return name


class LoginRequest(StrictBaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_input(cls, value: object) -> str:
        email = str(value).strip().lower()
        if not email:
            raise ValueError("Email is required.")
        return email

    @field_validator("password")
    @classmethod
    def validate_password_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Password must not be empty.")
        return value


class AuthUserResponse(StrictBaseModel):
    id: int
    email: EmailStr
    name: str


class SignupResponse(StrictBaseModel):
    message: str
    user: AuthUserResponse


class LoginResponse(StrictBaseModel):
    message: str
    access_token: str
    token_type: str = "bearer"
    user: AuthUserResponse
