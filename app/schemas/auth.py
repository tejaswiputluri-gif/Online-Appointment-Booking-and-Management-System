"""Auth request/response schemas."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    # Role selection at registration — admin typically provisioned by seed/ops
    role: Literal["patient", "doctor", "admin"] = "patient"
    # Required when role == doctor
    specialization: Optional[str] = Field(default=None, max_length=120)
    available_days: Optional[str] = Field(
        default="mon,tue,wed,thu,fri",
        description="Comma-separated weekdays, e.g. mon,tue,wed",
    )


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: int


class MessageResponse(BaseModel):
    detail: str

    model_config = ConfigDict(from_attributes=True)
