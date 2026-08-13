"""Request and response DTOs for administrator and customer authentication."""

from pydantic import BaseModel, Field


class AdminLoginRequest(BaseModel):
    """Credentials for the single shared administrator account."""

    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=500)


class CustomerAccessVerifyRequest(BaseModel):
    """One opaque customer access-link token."""

    token: str = Field(min_length=1, max_length=500)
