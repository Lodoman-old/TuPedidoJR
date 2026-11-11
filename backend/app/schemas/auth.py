from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=20)
    password: str = Field(..., min_length=6, max_length=128)
    address: str | None = None
    referral_code: str | None = Field(default=None, max_length=20)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    password: str = Field(..., min_length=6, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    is_superuser: bool = False


class UserOut(BaseModel):
    id: UUID
    name: str
    email: str
    phone: str | None
    address: str | None
    is_active: bool
    is_superuser: bool = False
    loyalty_points: int = 0
    referral_code: str | None = None

    class Config:
        from_attributes = True
