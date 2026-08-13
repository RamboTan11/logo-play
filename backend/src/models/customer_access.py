"""DTOs for the internal customer-access management page."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

CustomerAccessStatus = Literal["unstarted", "active", "stopped", "expired"]


class CustomerAccessDto(BaseModel):
    """The safe customer row returned to the internal page."""

    id: str
    name: str
    masked_access_url: str
    status: CustomerAccessStatus
    access_expires_at: datetime | None


class CustomerAccessListDto(BaseModel):
    """Filtered customer-access list result."""

    items: list[CustomerAccessDto]
    total: int


class CreateCustomerRequest(BaseModel):
    """Fields accepted by the compact new-customer dialog."""

    name: str = Field(min_length=1, max_length=200)
    validity_days: Literal[1, 3, 7] = 3
    activate_immediately: bool = False


class UpdateCustomerExpirationRequest(BaseModel):
    """The only editable field after a customer has been created."""

    access_expires_at: datetime
