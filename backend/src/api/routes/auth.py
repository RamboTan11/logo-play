"""Shared administrator login and customer access-link verification endpoints."""

from contextlib import suppress
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.deps import require_admin_session, require_customer_session
from src.api.errors import ApplicationHTTPException
from src.db.session import get_db
from src.models.auth import AdminLoginRequest, CustomerAccessVerifyRequest
from src.services.auth_service import (
    ADMIN_SESSION_COOKIE,
    CUSTOMER_SESSION_COOKIE,
    LEGACY_SESSION_COOKIE_PATH,
    SESSION_COOKIE_PATH,
    SESSION_MAX_AGE_SECONDS,
    AuthConfigurationError,
    AuthenticatedPrincipal,
    AuthService,
    InvalidCredentialsError,
    utc_now,
)
from src.services.customer_access_service import (
    CustomerAccessService,
    CustomerAccessStateError,
    InvalidAccessLinkError,
)

from pycore.api import success_response
from pycore.api.responses import APIResponse

router = APIRouter(prefix="/api/v1", tags=["authentication"])
DatabaseDependency = Annotated[AsyncSession, Depends(get_db)]
AdminSessionDependency = Annotated[AuthenticatedPrincipal, Depends(require_admin_session)]
CustomerSessionDependency = Annotated[AuthenticatedPrincipal, Depends(require_customer_session)]


def _secure_cookie(request: Request) -> bool:
    """Use Secure cookies only when the browser-facing request is HTTPS.

    Production is expected to terminate TLS before this service, while local
    pre-production runs on loopback HTTP. Browsers such as Safari reject a
    Secure cookie received over HTTP, so environment alone is insufficient.
    """

    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    return (forwarded_proto or request.url.scheme).lower() == "https"


@router.post("/admin/auth/login")
async def login_admin(
    payload: AdminLoginRequest,
    request: Request,
    response: Response,
    session: DatabaseDependency,
) -> APIResponse:
    """Exchange the shared username/password for a browser-only admin session."""

    service = AuthService(request.app.state.settings)
    try:
        _, token, expires_at = await service.login_admin(
            session,
            username=payload.username,
            password=payload.password,
            trace_id=uuid4().hex,
        )
    except InvalidCredentialsError as error:
        await session.commit()
        raise ApplicationHTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Username or password is incorrect",
            "invalid_credentials",
        ) from error
    except AuthConfigurationError as error:
        raise ApplicationHTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Administrator authentication is unavailable",
            "auth_configuration_unavailable",
        ) from error
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE_SECONDS,
        expires=expires_at,
        path=SESSION_COOKIE_PATH,
        secure=_secure_cookie(request),
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(ADMIN_SESSION_COOKIE, path=LEGACY_SESSION_COOKIE_PATH, samesite="lax")
    response.headers["Cache-Control"] = "private, no-store"
    return success_response(data={"authenticated": True})


@router.get("/admin/auth/session")
async def get_admin_session(_: AdminSessionDependency) -> APIResponse:
    """Confirm that the browser still holds a live admin session."""

    return success_response(data={"authenticated": True})


@router.post("/admin/auth/logout")
async def logout_admin(
    request: Request,
    response: Response,
    session: DatabaseDependency,
) -> APIResponse:
    """Idempotently revoke and clear the current admin session."""

    with suppress(AuthConfigurationError):
        await AuthService(request.app.state.settings).logout_admin(
            session,
            request.cookies.get(ADMIN_SESSION_COOKIE),
            trace_id=uuid4().hex,
        )
    response.delete_cookie(ADMIN_SESSION_COOKIE, path=SESSION_COOKIE_PATH, samesite="lax")
    response.delete_cookie(ADMIN_SESSION_COOKIE, path=LEGACY_SESSION_COOKIE_PATH, samesite="lax")
    response.headers["Cache-Control"] = "private, no-store"
    return success_response(data={"logged_out": True})


@router.post("/auth/verify")
async def verify_customer_access(
    payload: CustomerAccessVerifyRequest,
    request: Request,
    response: Response,
    session: DatabaseDependency,
) -> APIResponse:
    """Exchange a valid current access link for a browser-only customer session."""

    auth = AuthService(request.app.state.settings)
    access = CustomerAccessService(request.app.state.settings, auth=auth)
    trace_id = uuid4().hex
    try:
        customer, link = await access.verify_access_token(session, payload.token, trace_id=trace_id)
        token, expires_at = await auth.issue_customer_session(
            session,
            customer=customer,
            access_link=link,
            trace_id=trace_id,
        )
    except InvalidAccessLinkError as error:
        await session.commit()
        raise ApplicationHTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Access link is invalid",
            "invalid_access_link",
            clear_cookie=CUSTOMER_SESSION_COOKIE,
        ) from error
    except CustomerAccessStateError as error:
        await session.commit()
        raise ApplicationHTTPException(
            status.HTTP_403_FORBIDDEN,
            "Customer access is unavailable",
            error.error_code,
            clear_cookie=CUSTOMER_SESSION_COOKIE,
        ) from error
    except AuthConfigurationError as error:
        raise ApplicationHTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Customer authentication is unavailable",
            "auth_configuration_unavailable",
        ) from error
    response.set_cookie(
        CUSTOMER_SESSION_COOKIE,
        token,
        max_age=max(0, int((expires_at - utc_now()).total_seconds())),
        expires=expires_at,
        path=SESSION_COOKIE_PATH,
        secure=_secure_cookie(request),
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(CUSTOMER_SESSION_COOKIE, path=LEGACY_SESSION_COOKIE_PATH, samesite="lax")
    response.headers["Cache-Control"] = "private, no-store"
    return success_response(data={"authenticated": True})


@router.get("/auth/session")
async def get_customer_session(_: CustomerSessionDependency) -> APIResponse:
    """Confirm that the browser still holds a live customer session."""

    return success_response(data={"authenticated": True})


@router.post("/auth/logout")
async def logout_customer(
    request: Request,
    response: Response,
    session: DatabaseDependency,
) -> APIResponse:
    """Idempotently revoke and clear the current customer session."""

    with suppress(AuthConfigurationError):
        await AuthService(request.app.state.settings).logout_customer(
            session,
            request.cookies.get(CUSTOMER_SESSION_COOKIE),
            trace_id=uuid4().hex,
        )
    response.delete_cookie(CUSTOMER_SESSION_COOKIE, path=SESSION_COOKIE_PATH, samesite="lax")
    response.delete_cookie(CUSTOMER_SESSION_COOKIE, path=LEGACY_SESSION_COOKIE_PATH, samesite="lax")
    response.headers["Cache-Control"] = "private, no-store"
    return success_response(data={"logged_out": True})
