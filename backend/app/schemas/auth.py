from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=20)
    password: str = Field(..., min_length=6, max_length=128)
    address: str | None = None
    referral_code: str | None = Field(default=None, max_length=20)
    # Honeypot: los humanos lo dejan vacío.
    website: str | None = Field(default=None, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class VerifyEmailRequest(BaseModel):
    token: str = Field(..., min_length=10)


class ResetPasswordRequest(BaseModel):
    token: str
    password: str = Field(..., min_length=6, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    is_superuser: bool = False


class TwoFactorRequired(BaseModel):
    requires_2fa: bool = True
    temp_token: str


class TwoFactorVerifyRequest(BaseModel):
    temp_token: str = Field(..., min_length=10)
    code: str = Field(..., min_length=4, max_length=20)


class TwoFactorSetupOut(BaseModel):
    secret: str
    otpauth_uri: str
    qr_svg: str = ""
    recovery_codes: list[str] = []


class TwoFactorCodeRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=20)


class TwoFactorDisableRequest(BaseModel):
    password: str
    code: str | None = Field(default=None, max_length=20)


class UserOut(BaseModel):
    id: UUID
    name: str
    email: str
    phone: str | None
    address: str | None
    is_active: bool
    is_superuser: bool = False
    email_verified: bool = False
    loyalty_points: int = 0
    pending_balance: Decimal = Decimal("0")
    pending_installments: int = 0
    installment_amount: Decimal = Decimal("0")
    referral_code: str | None = None

    class Config:
        from_attributes = True
