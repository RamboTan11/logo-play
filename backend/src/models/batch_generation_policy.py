"""DTOs for the internal batch image-generation strategy API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BatchPromptTemplateDto(BaseModel):
    """A prompt template with zero to eight equal, upload-ordered reference images."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    name: str = Field(default="", max_length=48)
    reference_images: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Ordered model_strategy_reference asset IDs; at most eight are accepted.",
    )
    positive_prompt: str = Field(default="", max_length=8_000)
    negative_prompt: str | None = Field(default=None, max_length=8_000)


class BatchStyleDto(BaseModel):
    """A batch style owns generation count and a set of complete template combinations."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    name: str = Field(default="", max_length=32)
    generation_count: int = Field(ge=0, le=9)
    templates: list[BatchPromptTemplateDto] = Field(default_factory=list)


class BatchPolicyPayload(BaseModel):
    """The only mutable batch-scene fields accepted from the internal page."""

    model_config = ConfigDict(extra="forbid")

    model_connection_id: str = Field(default="", max_length=64)
    styles: list[BatchStyleDto] = Field(default_factory=list, max_length=100)


class BatchPolicyVersionDto(BaseModel):
    """A read-only immutable batch policy snapshot."""

    id: str
    version: int
    model_connection_id: str
    styles_snapshot: list[BatchStyleDto]
    published_at: datetime


class BatchPolicyDataDto(BaseModel):
    """The persisted editor draft and the current published timestamp."""

    draft_seed: BatchPolicyPayload
    last_published_at: datetime | None = None
    draft_updated_at: datetime | None = None


class PolicyDraftSavedDto(BaseModel):
    """Acknowledgement returned after the editor draft is persisted."""

    draft_saved: Literal[True]
    saved_at: datetime


class PolicyPublishedDto(BaseModel):
    """Version-free acknowledgement returned to policy configuration pages."""

    published: Literal[True]


class StrategyValidationErrorDto(BaseModel):
    """One field-scoped policy validation message safe for the internal editor."""

    field: str
    code: Literal[
        "required",
        "unknown_template_variable",
        "required_template_variable",
        "invalid_reference_image",
        "unverified_model_connection",
        "invalid_generation_count",
    ]
    message: str


class ReferenceImageAssetDto(BaseModel):
    """Reference-image metadata excluding any storage address or data URL."""

    id: str
    filename: str
    mime_type: Literal["image/jpeg", "image/png", "image/webp"]
    size_bytes: int
    content_hash: str
    version: Literal[1]
    created_at: datetime
