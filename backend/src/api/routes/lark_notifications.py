"""Administrator-protected Lark notification configuration endpoints."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.deps import require_admin_session
from src.api.errors import ApplicationHTTPException
from src.db.session import get_db
from src.models.lark_notification import (
    LarkChannelUpdate,
    LarkNotificationRuleBatchUpdate,
    LarkNotificationRuleUpdate,
    LarkRecipientCreate,
    LarkRecipientUpdate,
    LarkTestRequest,
)
from src.services.auth_service import AuthenticatedPrincipal
from src.services.lark_notification_service import LarkNotificationError, LarkNotificationService
from src.services.lark_secret_service import LarkSecretConfigurationError

from pycore.api import success_response
from pycore.api.responses import APIResponse, error_response

router = APIRouter(prefix="/api/v1", tags=["lark-notifications"])

AdminDependency = Annotated[AuthenticatedPrincipal, Depends(require_admin_session)]
DatabaseDependency = Annotated[AsyncSession, Depends(get_db)]


def get_lark_service(request: Request) -> LarkNotificationService:
    try:
        return LarkNotificationService(
            request.app.state.settings,
            client=getattr(request.app.state, "lark_webhook_client", None),
        )
    except LarkSecretConfigurationError as error:
        raise ApplicationHTTPException(
            503,
            "Lark 安全配置不可用",
            "lark_configuration_unavailable",
        ) from error


ServiceDependency = Annotated[LarkNotificationService, Depends(get_lark_service)]


def _safe_error(error: LarkNotificationError | LarkSecretConfigurationError) -> JSONResponse:
    if isinstance(error, LarkSecretConfigurationError):
        code, message, status_code = (
            "lark_configuration_unavailable",
            "Lark 安全配置不可用",
            503,
        )
    else:
        code, message, status_code = error.code, str(error), error.status_code
    body, http_status = error_response(message, error_code=code, status_code=status_code)
    return JSONResponse(status_code=http_status, content=body.model_dump())


@router.get("/notification-channels/lark", response_model=None)
async def get_channel(
    _: AdminDependency, session: DatabaseDependency, service: ServiceDependency
) -> APIResponse | JSONResponse:
    try:
        result = await service.get_channel(session)
    except (LarkNotificationError, LarkSecretConfigurationError) as error:
        return _safe_error(error)
    return success_response(data=result.model_dump(mode="json"))


@router.put("/notification-channels/lark", response_model=None)
async def update_channel(
    payload: LarkChannelUpdate,
    principal: AdminDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
) -> APIResponse | JSONResponse:
    try:
        result = await service.update_channel(session, payload, principal.id)
    except (LarkNotificationError, LarkSecretConfigurationError) as error:
        return _safe_error(error)
    return success_response(data=result.model_dump(mode="json"))


@router.post("/notification-channels/lark/test", response_model=None)
async def test_channel(
    payload: LarkTestRequest,
    principal: AdminDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
) -> APIResponse | JSONResponse:
    try:
        result = await service.test_channel(session, payload, principal.id)
    except (LarkNotificationError, LarkSecretConfigurationError) as error:
        return _safe_error(error)
    return success_response(data=result.model_dump(mode="json"))


@router.get("/notification-recipients/lark", response_model=None)
async def list_recipients(
    _: AdminDependency, session: DatabaseDependency, service: ServiceDependency
) -> APIResponse | JSONResponse:
    try:
        result = await service.list_recipients(session)
    except (LarkNotificationError, LarkSecretConfigurationError) as error:
        return _safe_error(error)
    return success_response(data=[item.model_dump(mode="json") for item in result])


@router.post("/notification-recipients/lark", status_code=201, response_model=None)
async def create_recipient(
    payload: LarkRecipientCreate,
    principal: AdminDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
) -> APIResponse | JSONResponse:
    try:
        result = await service.create_recipient(session, payload, principal.id)
    except (LarkNotificationError, LarkSecretConfigurationError) as error:
        return _safe_error(error)
    return success_response(data=result.model_dump(mode="json"), code=201)


@router.patch("/notification-recipients/lark/{recipient_id}", response_model=None)
async def update_recipient(
    recipient_id: str,
    payload: LarkRecipientUpdate,
    principal: AdminDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
) -> APIResponse | JSONResponse:
    try:
        result = await service.update_recipient(session, recipient_id, payload, principal.id)
    except (LarkNotificationError, LarkSecretConfigurationError) as error:
        return _safe_error(error)
    return success_response(data=result.model_dump(mode="json"))


@router.delete("/notification-recipients/lark/{recipient_id}", response_model=None)
async def delete_recipient(
    recipient_id: str,
    principal: AdminDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
) -> APIResponse | JSONResponse:
    try:
        await service.delete_recipient(session, recipient_id, principal.id)
    except (LarkNotificationError, LarkSecretConfigurationError) as error:
        return _safe_error(error)
    return success_response(data={"deleted": True})


@router.get("/notification-rules/lark", response_model=None)
async def list_rules(
    _: AdminDependency, session: DatabaseDependency, service: ServiceDependency
) -> APIResponse | JSONResponse:
    try:
        result = await service.list_rules(session)
    except (LarkNotificationError, LarkSecretConfigurationError) as error:
        return _safe_error(error)
    return success_response(data=[item.model_dump(mode="json") for item in result])


@router.put("/notification-rules/lark", response_model=None)
async def update_rules(
    payload: LarkNotificationRuleBatchUpdate,
    principal: AdminDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
) -> APIResponse | JSONResponse:
    try:
        result = await service.update_rules(session, payload, principal.id)
    except (LarkNotificationError, LarkSecretConfigurationError) as error:
        return _safe_error(error)
    return success_response(data=[item.model_dump(mode="json") for item in result])


@router.put("/notification-rules/lark/{event_type}", response_model=None)
async def update_rule(
    event_type: str,
    payload: LarkNotificationRuleUpdate,
    principal: AdminDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
) -> APIResponse | JSONResponse:
    try:
        result = await service.update_rule(session, event_type, payload, principal.id)
    except (LarkNotificationError, LarkSecretConfigurationError) as error:
        return _safe_error(error)
    return success_response(data=result.model_dump(mode="json"))


@router.get("/notification-deliveries/lark/recent", response_model=None)
async def recent_deliveries(
    _: AdminDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
    status: Annotated[Literal["all", "retrying", "failed"], Query()] = "all",
    limit: Annotated[int, Query(ge=1, le=10)] = 10,
) -> APIResponse | JSONResponse:
    try:
        result = await service.recent_deliveries(session, status=status, limit=limit)
    except (LarkNotificationError, LarkSecretConfigurationError) as error:
        return _safe_error(error)
    return success_response(data=result.model_dump(mode="json"))
