"""Customer-facing DTOs for saved Logos and adopted design tasks."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DesignTaskStatus = Literal["waiting_assignment", "in_progress", "completed", "canceled"]
CustomerAccessStatus = Literal["unstarted", "active", "stopped", "expired"]


class SaveLogoRequestDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logo_version_id: str = Field(min_length=1, max_length=64)


class UpdateSavedLogoRequestDto(SaveLogoRequestDto):
    """Replace the immutable version referenced by one saved-logo record."""


class AdoptLogoRequestDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logo_version_id: str = Field(min_length=1, max_length=64)
    adoption_suggestion: str | None = Field(default=None, max_length=4000)
    confirm_replace_active_task: bool = False


class TaskFeedbackRequestDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback: str | None = Field(default=None, max_length=4000)
    rating: int | None = Field(default=None, ge=1, le=5)

    @model_validator(mode="after")
    def require_value(self) -> "TaskFeedbackRequestDto":
        if self.feedback is None and self.rating is None:
            raise ValueError("feedback or rating is required")
        return self


class SavedLogoDto(BaseModel):
    id: str
    logo_version_id: str
    domain: str
    image_url: str
    saved_at: datetime


class SavedLogoMutationDto(BaseModel):
    saved_logo: SavedLogoDto
    created: bool


class SavedLogoListDto(BaseModel):
    items: list[SavedLogoDto]
    total: int


class DesignTaskSummaryDto(BaseModel):
    id: str
    domain: str
    status: DesignTaskStatus
    adoption_suggestion: str | None
    customer_feedback: str | None
    rating: int | None
    submitted_at: datetime
    adopted_logo_version_id: str
    adopted_image_url: str
    delivery_image_url: str | None = None
    delivery_uploaded_at: datetime | None = None


class DesignTaskDetailDto(DesignTaskSummaryDto):
    adopted_logo_version_id: str
    adopted_image_url: str
    initial_logo_version_id: str
    initial_image_url: str
    ai_edit_inputs: list[str]
    delivery_image_url: str | None = None


class DesignTaskMutationDto(BaseModel):
    task: DesignTaskSummaryDto
    created: bool


class TaskFeedbackMutationDto(BaseModel):
    task: DesignTaskSummaryDto


class DesignTaskListDto(BaseModel):
    items: list[DesignTaskSummaryDto]
    total: int


class DesignTaskDetailResponseDto(BaseModel):
    task: DesignTaskDetailDto


class AdminDesignTaskListItemDto(BaseModel):
    id: str
    customer_name: str
    domain: str
    status: DesignTaskStatus
    adoption_suggestion: str | None
    customer_feedback: str | None
    rating: int | None
    submitted_at: datetime
    customer_access_status: CustomerAccessStatus


class AdminDesignTaskListDto(BaseModel):
    items: list[AdminDesignTaskListItemDto]
    total: int
    page: int
    page_size: int


class AdminDesignTaskDetailDto(AdminDesignTaskListItemDto):
    adopted_image_url: str
    delivery_image_url: str | None = None


class AdminDesignTaskDetailResponseDto(BaseModel):
    task: AdminDesignTaskDetailDto
