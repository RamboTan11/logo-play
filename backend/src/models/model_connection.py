"""Public DTOs for model connection management."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

ConnectionStatus = Literal["untested", "verified", "failed", "fallback_unverified"]
VerificationMode = Literal["real"]


class ModelCapabilityDto(BaseModel):
    """A capability verified through a real controlled test only."""

    capability: Literal["image_to_image"]
    verified: bool
    verification_mode: VerificationMode
    verified_at: datetime | None


class ModelConnectionDto(BaseModel):
    """Safe connection shape returned to internal UI clients."""

    id: str
    provider: str
    model_id: str
    max_input_images: int | None
    api_url: str
    region_or_workspace: str | None
    credential_status: Literal["configured", "missing"]
    api_key_masked: str | None
    connection_status: ConnectionStatus
    verified_capabilities: list[ModelCapabilityDto]
    version: int
    updated_at: datetime


class CreateModelConnectionRequest(BaseModel):
    """A new connection accepts its API Key exactly once."""

    provider: str = Field(min_length=1, max_length=64)
    model_id: str = Field(min_length=1, max_length=128)
    api_url: HttpUrl
    region_or_workspace: str | None = Field(default=None, max_length=128)
    api_key: str = Field(min_length=1, max_length=4096)
    max_input_images: int = Field(default=9, ge=0, le=9)


class UpdateModelConnectionRequest(BaseModel):
    """An omitted or blank API Key keeps the already encrypted value."""

    provider: str = Field(min_length=1, max_length=64)
    model_id: str = Field(min_length=1, max_length=128)
    api_url: HttpUrl
    region_or_workspace: str | None = Field(default=None, max_length=128)
    api_key: str | None = Field(default=None, max_length=4096)
    max_input_images: int | None = Field(default=None, ge=0, le=9)


class ModelConnectionTestData(BaseModel):
    """A test result exposes only safe provider diagnostics and no supplier payload."""

    connection: ModelConnectionDto
    result: ConnectionStatus
    message: str
    trace_id: str
    error_code: str | None = None
    provider_status_family: Literal["http_4xx", "http_5xx"] | None = None
    provider_http_status: int | None = None
    response_image_count: int | None = None
    duration_ms: int = 0
    diagnostic_capture_status: Literal["not_attempted", "captured", "failed"] = "not_attempted"
