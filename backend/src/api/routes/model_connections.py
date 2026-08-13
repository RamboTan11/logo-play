"""Internal-admin API for model connections and controlled testing."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.deps import require_admin
from src.db.session import get_db
from src.models.model_connection import CreateModelConnectionRequest, UpdateModelConnectionRequest
from src.services.auth_service import AuthenticatedPrincipal
from src.services.model_connection_service import ModelConnectionInUseError, ModelConnectionService
from src.services.model_secret_service import SecretConfigurationError

from pycore.api import success_response
from pycore.api.responses import APIResponse

router = APIRouter(prefix="/api/v1/model-connections", tags=["model-connections"])


def get_model_connection_service(request: Request) -> ModelConnectionService:
    """Build the service from application-scoped configuration."""

    return ModelConnectionService(
        request.app.state.settings,
        provider=getattr(request.app.state, "model_connection_provider", None),
        diagnostics=getattr(request.app.state, "controlled_smoke_diagnostic_store", None),
    )


ServiceDependency = Annotated[ModelConnectionService, Depends(get_model_connection_service)]
AdminDependency = Annotated[AuthenticatedPrincipal, Depends(require_admin)]
DatabaseDependency = Annotated[AsyncSession, Depends(get_db)]


@router.get("")
async def list_model_connections(
    _: AdminDependency, session: DatabaseDependency, service: ServiceDependency
) -> APIResponse:
    """List only safe connection metadata."""

    try:
        connections = await service.list(session)
    except SecretConfigurationError as error:
        raise HTTPException(status_code=503, detail="Secret encryption configuration is unavailable") from error
    return success_response(data=[item.model_dump(mode="json") for item in connections])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_model_connection(
    payload: CreateModelConnectionRequest,
    principal: AdminDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
) -> APIResponse:
    """Store a one-time Key write as authenticated encrypted ciphertext."""

    try:
        created = await service.create(session, payload, principal.id)
    except SecretConfigurationError as error:
        raise HTTPException(status_code=503, detail="Secret encryption configuration is unavailable") from error
    return success_response(data=created.model_dump(mode="json"), code=201)


@router.patch("/{connection_id}")
async def update_model_connection(
    connection_id: str,
    payload: UpdateModelConnectionRequest,
    principal: AdminDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
) -> APIResponse:
    """Update metadata and optionally rotate a Key without reading it back."""

    try:
        updated = await service.update(session, connection_id, payload, principal.id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="Model connection not found") from error
    except SecretConfigurationError as error:
        raise HTTPException(status_code=503, detail="Secret encryption configuration is unavailable") from error
    return success_response(data=updated.model_dump(mode="json"))


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model_connection(
    connection_id: str,
    principal: AdminDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
) -> None:
    """Retire a connection while preserving historical policy snapshots."""

    try:
        await service.delete(session, connection_id, principal.id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="Model connection not found") from error
    except ModelConnectionInUseError as error:
        raise HTTPException(
            status_code=409,
            detail="该模型连接正在被当前生效策略使用，请先替换模型并发布策略后再删除。",
        ) from error


@router.post("/{connection_id}/test")
async def test_model_connection(
    connection_id: str,
    principal: AdminDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
) -> APIResponse:
    """Run a server-controlled test with no client body or provider parameters."""

    try:
        tested = await service.test(session, connection_id, principal.id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="Model connection not found") from error
    except SecretConfigurationError as error:
        raise HTTPException(status_code=503, detail="Secret encryption configuration is unavailable") from error
    return success_response(data=tested.model_dump(mode="json"))
