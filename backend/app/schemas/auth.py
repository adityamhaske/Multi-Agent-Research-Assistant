from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.services.passwords import MIN_LENGTH


class RegisterRequest(BaseModel):
    email: EmailStr
    # Policy enforced in the service (breached-list + byte limit); length floor here.
    password: str = Field(min_length=MIN_LENGTH, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: UUID
    email: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
