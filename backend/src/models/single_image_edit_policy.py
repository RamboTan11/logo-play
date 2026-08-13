"""DTOs for the internal single-image-edit strategy API."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SingleImageEditPolicyPayload(BaseModel):
    """The browser-editable business fields for the single-image scene."""

    model_config = ConfigDict(extra="forbid")

    model_connection_id: str = Field(default="", max_length=64)
    positive_content: str = Field(default="", max_length=8_000)
    negative_avoidance: str = Field(default="", max_length=8_000)


class SingleImageEditPolicyVersionDto(SingleImageEditPolicyPayload):
    """A public read-only view of one immutable single-image policy snapshot."""

    id: str
    version: int
    published_at: datetime
    compiler_contract: dict[str, object] | None = None


class SingleImageEditPolicyDataDto(BaseModel):
    """A browser-editable seed copied from the current internal snapshot."""

    draft_seed: SingleImageEditPolicyPayload
