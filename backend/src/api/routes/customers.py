"""Internal customer-access management endpoints."""

from collections.abc import Awaitable, Callable
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.deps import require_admin
from src.api.errors import ApplicationHTTPException
from src.db.session import get_db
from src.models.customer_access import (
    CreateCustomerRequest,
    CustomerAccessDto,
    UpdateCustomerExpirationRequest,
)
from src.services.auth_service import AuthConfigurationError, AuthenticatedPrincipal
from src.services.customer_access_service import (
    CustomerAccessNotFoundError,
    CustomerAccessService,
    CustomerAccessStateError,
    InvalidAccessExpirationError,
)

from pycore.api import success_response
from pycore.api.responses import APIResponse

router = APIRouter(prefix="/api/v1/customers", tags=["customer-access"])
AdminDependency = Annotated[AuthenticatedPrincipal, Depends(require_admin)]
DatabaseDependency = Annotated[AsyncSession, Depends(get_db)]


def _service(request: Request) -> CustomerAccessService:
    return CustomerAccessService(request.app.state.settings)


@router.get("")
async def list_customers(
    _: AdminDependency,
    session: DatabaseDependency,
    request: Request,
    search: Annotated[str, Query(max_length=200)] = "",
    status_filter: Annotated[
        Literal["all", "unstarted", "active", "stopped", "expired"],
        Query(alias="status"),
    ] = "all",
) -> APIResponse:
    """Search and filter the formal customer access list."""

    try:
        items = await _service(request).list_customers(
            session, search=search, status_filter=status_filter
        )
    except AuthConfigurationError as error:
        raise _configuration_error(error) from error
    return success_response(
        data={"items": [item.model_dump(mode="json") for item in items], "total": len(items)}
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CreateCustomerRequest,
    principal: AdminDependency,
    session: DatabaseDependency,
    request: Request,
) -> APIResponse:
    """Create a formal customer and its one current access link."""

    try:
        customer = await _service(request).create_customer(
            session,
            name=payload.name,
            validity_days=payload.validity_days,
            activate_immediately=payload.activate_immediately,
            actor_id=principal.id,
            trace_id=uuid4().hex,
        )
    except ValueError as error:
        raise ApplicationHTTPException(422, str(error), "validation_error") from error
    except AuthConfigurationError as error:
        raise _configuration_error(error) from error
    return success_response(data={"customer": customer.model_dump(mode="json")}, code=201)


@router.post("/{customer_id}/enable")
async def enable_customer(
    customer_id: str,
    principal: AdminDependency,
    session: DatabaseDependency,
    request: Request,
) -> APIResponse:
    """Activate an unstarted customer's configured validity duration."""

    customer = await _run_customer_action(
        _service(request).enable,
        session,
        customer_id,
        actor_id=principal.id,
        trace_id=uuid4().hex,
    )
    return success_response(data={"customer": customer.model_dump(mode="json")})


@router.patch("/{customer_id}/access-expiration")
async def update_customer_expiration(
    customer_id: str,
    payload: UpdateCustomerExpirationRequest,
    principal: AdminDependency,
    session: DatabaseDependency,
    request: Request,
) -> APIResponse:
    """Edit only the future expiration of an active or stopped customer."""

    try:
        customer = await _service(request).update_expiration(
            session,
            customer_id,
            access_expires_at=payload.access_expires_at,
            actor_id=principal.id,
            trace_id=uuid4().hex,
        )
    except InvalidAccessExpirationError as error:
        raise ApplicationHTTPException(422, str(error), "invalid_access_expiration") from error
    except CustomerAccessNotFoundError as error:
        raise ApplicationHTTPException(404, "Customer not found", "not_found") from error
    except CustomerAccessStateError as error:
        raise ApplicationHTTPException(409, str(error), error.error_code) from error
    except AuthConfigurationError as error:
        raise _configuration_error(error) from error
    return success_response(data={"customer": customer.model_dump(mode="json")})


@router.post("/{customer_id}/stop")
async def stop_customer(
    customer_id: str,
    principal: AdminDependency,
    session: DatabaseDependency,
    request: Request,
) -> APIResponse:
    """Stop access and revoke all current customer sessions immediately."""

    customer = await _run_customer_action(
        _service(request).stop,
        session,
        customer_id,
        actor_id=principal.id,
        trace_id=uuid4().hex,
    )
    return success_response(data={"customer": customer.model_dump(mode="json")})


@router.post("/{customer_id}/resume")
async def resume_customer(
    customer_id: str,
    principal: AdminDependency,
    session: DatabaseDependency,
    request: Request,
) -> APIResponse:
    """Resume stopped access without changing the existing expiration."""

    customer = await _run_customer_action(
        _service(request).resume,
        session,
        customer_id,
        actor_id=principal.id,
        trace_id=uuid4().hex,
    )
    return success_response(data={"customer": customer.model_dump(mode="json")})


@router.post("/{customer_id}/access-link/copy", response_class=JSONResponse)
async def copy_customer_access_url(
    customer_id: str,
    principal: AdminDependency,
    session: DatabaseDependency,
    request: Request,
) -> JSONResponse:
    """Return the complete existing URL only to the clipboard action."""

    try:
        access_url = await _service(request).copy_access_url(
            session,
            customer_id,
            actor_id=principal.id,
            trace_id=uuid4().hex,
        )
    except CustomerAccessNotFoundError as error:
        raise ApplicationHTTPException(404, "Customer not found", "not_found") from error
    except AuthConfigurationError as error:
        raise _configuration_error(error) from error
    body = success_response(data={"access_url": access_url}).model_dump(mode="json")
    return JSONResponse(
        content=body,
        headers={"Cache-Control": "private, no-store", "Pragma": "no-cache"},
    )


async def _run_customer_action(
    action: Callable[..., Awaitable[CustomerAccessDto]],
    session: AsyncSession,
    customer_id: str,
    **kwargs: str,
) -> CustomerAccessDto:
    try:
        return await action(session, customer_id, **kwargs)
    except CustomerAccessNotFoundError as error:
        raise ApplicationHTTPException(404, "Customer not found", "not_found") from error
    except CustomerAccessStateError as error:
        raise ApplicationHTTPException(409, str(error), error.error_code) from error
    except AuthConfigurationError as error:
        raise _configuration_error(error) from error


def _configuration_error(error: Exception) -> ApplicationHTTPException:
    del error
    return ApplicationHTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Customer access configuration is unavailable",
        "auth_configuration_unavailable",
    )
