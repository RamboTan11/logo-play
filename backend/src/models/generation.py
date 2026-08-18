"""Customer-facing DTOs for the T-013 batch generation runtime."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

GenerationStatus = Literal["processing", "succeeded", "failed"]
DomainSuffix = Literal[".com", ".game", ".win", ".app"]


class BatchGenerationRequestDto(BaseModel):
    """The only customer-controlled input for a batch image request."""

    model_config = ConfigDict(extra="forbid")

    domain_label: str = Field(min_length=1, max_length=250)
    domain_suffix: DomainSuffix
    source_image_asset_id: str | None = Field(default=None, min_length=1, max_length=64)
    user_reference_requirement: str | None = Field(default=None, max_length=2_000)

    @field_validator("domain_label", mode="before")
    @classmethod
    def trim_domain_label(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class BatchGenerationAcceptedDto(BaseModel):
    """A persisted request that has been accepted for recoverable execution."""

    request_id: str
    target_count: int
    created_candidate_jobs: int
    status: Literal["processing"]


class GeneratedLogoVersionDto(BaseModel):
    """A customer-owned image with a protected server-generated retrieval URL."""

    id: str
    image_url: str


class GenerationCandidateFailureDto(BaseModel):
    code: str
    message: str


class GenerationCandidateSlotDto(BaseModel):
    slot_index: int
    status: Literal["succeeded", "failed"]
    logo_version_id: str | None = None
    image_url: str | None = None
    failure: GenerationCandidateFailureDto | None = None
    retry_token: str | None = None


class GenerationSlotRetryRequestDto(BaseModel):
    """Opaque server-issued authority to retry exactly one failed slot."""

    model_config = ConfigDict(extra="forbid")

    retry_token: str = Field(min_length=32, max_length=512)


class GenerationSlotRetryAcceptedDto(BaseModel):
    request_id: str
    slot_index: int
    status: Literal["processing"]


class GenerationBatchDto(BaseModel):
    """One immutable successful batch in the customer's result history."""

    request_id: str
    domain: str
    domain_label: str
    domain_suffix: DomainSuffix
    target_count: int
    status: GenerationStatus
    created_at: datetime
    logo_versions: list[GeneratedLogoVersionDto]

    candidates: list[GenerationCandidateSlotDto] = Field(default_factory=list)

class GenerationStatusDto(BaseModel):
    """The server-owned request status plus all successful batches in the history."""

    request_id: str
    domain: str
    domain_label: str
    domain_suffix: DomainSuffix
    target_count: int
    status: GenerationStatus
    error_code: str | None = None
    failure_summary: dict[str, object] | None = None
    batches: list[GenerationBatchDto]


class LatestSuccessfulGenerationDto(BaseModel):
    """The latest customer-owned successful generation, when one exists."""

    latest: GenerationStatusDto | None


class SingleImageEditRequestDto(BaseModel):
    """The customer-controlled input for one new immutable edit version."""

    model_config = ConfigDict(extra="forbid")

    source_version_id: str = Field(min_length=1, max_length=64)
    edit_instruction: str = Field(min_length=1, max_length=2_000)


class SingleImageEditAcceptedDto(BaseModel):
    request_id: str
    source_version_id: str
    status: Literal["processing"]


class SingleImageEditVersionDto(BaseModel):
    id: str
    version_number: int
    edit_instruction: str | None = None
    image_url: str


class SingleImageEditContextDto(BaseModel):
    root_version_id: str
    domain: str
    current_version_id: str
    versions: list[SingleImageEditVersionDto]


class SingleImageEditStatusDto(BaseModel):
    request_id: str
    source_version_id: str
    root_version_id: str
    domain: str
    status: GenerationStatus
    error_code: str | None = None
    current_version_id: str
    versions: list[SingleImageEditVersionDto]
