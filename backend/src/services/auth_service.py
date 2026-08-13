"""Shared administrator and customer browser-session authentication."""

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.config import AppSettings
from src.db.models import (
    AdminSession,
    Customer,
    CustomerAccessLink,
    CustomerSession,
    SharedAdministrator,
)
from src.services.event_service import EventService

ADMIN_SESSION_COOKIE = "logo_admin_session"
CUSTOMER_SESSION_COOKIE = "logo_customer_session"
SESSION_COOKIE_PATH = "/"
LEGACY_SESSION_COOKIE_PATH = "/api/v1"
SESSION_MAX_AGE_SECONDS = 12 * 60 * 60
_PASSWORD_SCHEME = "scrypt-v1"
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_LENGTH = 32


class AuthConfigurationError(RuntimeError):
    """Required private authentication configuration is unavailable or invalid."""


class InvalidCredentialsError(RuntimeError):
    """The shared administrator credential pair did not match."""


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """The minimal identity passed from route dependencies to business services."""

    id: str
    role: str


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""

    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Normalize SQLite's timezone-naive values to aware UTC."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def hash_password(password: str) -> str:
    """Hash an administrator password with a random salt and memory-hard Scrypt."""

    salt = secrets.token_bytes(16)
    derived = _derive_password(password, salt)
    return "$".join(
        (
            _PASSWORD_SCHEME,
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(derived).decode("ascii"),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    """Verify a password without exposing whether parsing or comparison failed."""

    try:
        scheme, salt_value, expected_value = encoded.split("$", 2)
        if scheme != _PASSWORD_SCHEME:
            return False
        salt = base64.urlsafe_b64decode(salt_value.encode("ascii"))
        expected = base64.urlsafe_b64decode(expected_value.encode("ascii"))
        actual = _derive_password(password, salt)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def _derive_password(password: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=_SCRYPT_LENGTH, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return cast(bytes, kdf.derive(password.encode("utf-8")))


class AuthService:
    """Create and validate independent admin and customer server-side sessions."""

    def __init__(self, settings: AppSettings, events: EventService | None = None) -> None:
        self.settings = settings
        self.events = events or EventService()

    async def initialize_shared_administrator(self, session: AsyncSession) -> None:
        """Bootstrap exactly one administrator only when the table is empty."""

        administrator = await session.scalar(select(SharedAdministrator).limit(1))
        if administrator is not None:
            return
        username = (self.settings.initial_admin_username or "").strip()
        password = self.settings.initial_admin_password or ""
        if not username or not password:
            return
        if len(username) > 100 or len(password) < 8:
            raise AuthConfigurationError("Initial administrator configuration is invalid")
        session.add(
            SharedAdministrator(
                id=uuid4().hex,
                username=username,
                password_hash=hash_password(password),
            )
        )

    async def login_admin(
        self,
        session: AsyncSession,
        *,
        username: str,
        password: str,
        trace_id: str,
    ) -> tuple[AuthenticatedPrincipal, str, datetime]:
        """Validate the shared account and issue a server-side session token."""

        self._session_secret()
        administrator = await session.scalar(select(SharedAdministrator).limit(1))
        if administrator is None:
            raise AuthConfigurationError("Shared administrator has not been initialized")
        valid = hmac.compare_digest(
            username.strip().encode("utf-8"), administrator.username.encode("utf-8")
        )
        valid = verify_password(password, administrator.password_hash) and valid
        if not valid:
            await self.events.record_audit(
                session,
                action="admin.auth.login_failed",
                resource_type="shared_administrator",
                resource_id="shared-admin",
                actor_id=None,
                trace_id=trace_id,
                summary={"username": username.strip(), "result": "rejected"},
            )
            raise InvalidCredentialsError

        token, token_hash = self._new_session_token()
        expires_at = utc_now() + timedelta(seconds=SESSION_MAX_AGE_SECONDS)
        session.add(
            AdminSession(
                id=uuid4().hex,
                token_hash=token_hash,
                administrator_id=administrator.id,
                expires_at=expires_at,
            )
        )
        await self.events.record_audit(
            session,
            action="admin.auth.login_succeeded",
            resource_type="shared_administrator",
            resource_id=administrator.id,
            actor_id=administrator.id,
            trace_id=trace_id,
            summary={"username": administrator.username, "result": "authenticated"},
        )
        return AuthenticatedPrincipal(administrator.id, "admin"), token, expires_at

    async def get_admin_principal(
        self, session: AsyncSession, token: str | None
    ) -> AuthenticatedPrincipal | None:
        """Resolve a live admin session from its browser-only token."""

        if not token:
            return None
        session_hash = self._hash_token(token)
        record = await session.scalar(
            select(AdminSession).where(AdminSession.token_hash == session_hash)
        )
        if record is None or not hmac.compare_digest(record.token_hash, session_hash):
            return None
        if record.revoked_at is not None or as_utc(record.expires_at) <= utc_now():
            return None
        administrator = await session.get(SharedAdministrator, record.administrator_id)
        if administrator is None:
            return None
        return AuthenticatedPrincipal(administrator.id, "admin")

    async def logout_admin(
        self, session: AsyncSession, token: str | None, *, trace_id: str
    ) -> None:
        """Revoke the current admin session if it exists."""

        record = await self._admin_session(session, token)
        if record is not None and record.revoked_at is None:
            record.revoked_at = utc_now()
            await self.events.record_audit(
                session,
                action="admin.auth.logout",
                resource_type="admin_session",
                resource_id=record.id,
                actor_id=record.administrator_id,
                trace_id=trace_id,
                summary={"result": "revoked"},
            )

    async def issue_customer_session(
        self,
        session: AsyncSession,
        *,
        customer: Customer,
        access_link: CustomerAccessLink,
        trace_id: str,
    ) -> tuple[str, datetime]:
        """Issue a customer session capped by both 12 hours and access expiry."""

        if customer.access_expires_at is None:
            raise AuthConfigurationError("Customer access expiration is unavailable")
        token, token_hash = self._new_session_token()
        expires_at = min(
            utc_now() + timedelta(seconds=SESSION_MAX_AGE_SECONDS),
            as_utc(customer.access_expires_at),
        )
        session.add(
            CustomerSession(
                id=uuid4().hex,
                token_hash=token_hash,
                customer_id=customer.id,
                source_access_link_id=access_link.id,
                expires_at=expires_at,
            )
        )
        await self.events.record_audit(
            session,
            action="customer.auth.verified",
            resource_type="customer_access_link",
            resource_id=access_link.id,
            actor_id=customer.id,
            trace_id=trace_id,
            summary={"result": "authenticated"},
        )
        return token, expires_at

    async def get_customer_principal(
        self, session: AsyncSession, token: str | None
    ) -> AuthenticatedPrincipal | None:
        """Resolve a customer session and recheck its current access state."""

        record = await self._customer_session(session, token)
        if record is None or record.revoked_at is not None:
            return None
        now = utc_now()
        if as_utc(record.expires_at) <= now:
            return None
        customer = await session.get(Customer, record.customer_id)
        if customer is None or customer.is_development_seed:
            return None
        if customer.access_state != "active" or customer.access_expires_at is None:
            return None
        if as_utc(customer.access_expires_at) <= now:
            return None
        return AuthenticatedPrincipal(customer.id, "customer")

    async def logout_customer(
        self, session: AsyncSession, token: str | None, *, trace_id: str
    ) -> None:
        """Revoke the current customer session if it exists."""

        record = await self._customer_session(session, token)
        if record is not None and record.revoked_at is None:
            record.revoked_at = utc_now()
            await self.events.record_audit(
                session,
                action="customer.auth.logout",
                resource_type="customer_session",
                resource_id=record.id,
                actor_id=record.customer_id,
                trace_id=trace_id,
                summary={"result": "revoked"},
            )

    async def revoke_customer_sessions(self, session: AsyncSession, customer_id: str) -> None:
        """Revoke all sessions for a customer immediately after access is stopped."""

        now = utc_now()
        records = (
            await session.scalars(
                select(CustomerSession).where(
                    CustomerSession.customer_id == customer_id,
                    CustomerSession.revoked_at.is_(None),
                )
            )
        ).all()
        for record in records:
            record.revoked_at = now

    def hash_access_token(self, token: str) -> str:
        """Hash a high-entropy access token for lookup and constant-time verification."""

        return self._hash_token(token)

    def _new_session_token(self) -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        return token, self._hash_token(token)

    def _hash_token(self, token: str) -> str:
        return hmac.new(
            self._session_secret(), token.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def _session_secret(self) -> bytes:
        value = self.settings.auth_session_secret or ""
        if len(value.encode("utf-8")) < 32:
            raise AuthConfigurationError("Authentication session configuration is unavailable")
        return value.encode("utf-8")

    async def _admin_session(
        self, session: AsyncSession, token: str | None
    ) -> AdminSession | None:
        if not token:
            return None
        token_hash = self._hash_token(token)
        record = await session.scalar(
            select(AdminSession).where(AdminSession.token_hash == token_hash)
        )
        if record is None or not hmac.compare_digest(record.token_hash, token_hash):
            return None
        return record

    async def _customer_session(
        self, session: AsyncSession, token: str | None
    ) -> CustomerSession | None:
        if not token:
            return None
        token_hash = self._hash_token(token)
        record = await session.scalar(
            select(CustomerSession).where(CustomerSession.token_hash == token_hash)
        )
        if record is None or not hmac.compare_digest(record.token_hash, token_hash):
            return None
        return record
