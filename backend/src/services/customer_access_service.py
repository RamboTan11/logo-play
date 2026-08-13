"""Customer creation, access-link secrets, and lifecycle transitions."""

import hmac
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from src.config import AppSettings
from src.db.models import Customer, CustomerAccessLink
from src.models.customer_access import CustomerAccessDto, CustomerAccessStatus
from src.services.auth_service import AuthConfigurationError, AuthService, as_utc, utc_now
from src.services.event_service import EventService
from src.services.lark_notification_service import LarkWorkflowService


class CustomerAccessNotFoundError(LookupError):
    """A formal customer or its current access link does not exist."""


class CustomerAccessStateError(RuntimeError):
    """A requested transition is not permitted from the current derived state."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class InvalidAccessExpirationError(ValueError):
    """The expiration payload is missing a timezone or is not in the future."""


class InvalidAccessLinkError(RuntimeError):
    """An opaque customer access token did not match a current link."""


class CustomerAccessService:
    """Own the formal customer access list and current-link state machine."""

    def __init__(
        self,
        settings: AppSettings,
        auth: AuthService | None = None,
        events: EventService | None = None,
    ) -> None:
        self.settings = settings
        self.events = events or EventService()
        self.auth = auth or AuthService(settings, self.events)
        self._lark = LarkWorkflowService(self.events)

    async def list_customers(
        self,
        session: AsyncSession,
        *,
        search: str,
        status_filter: str,
    ) -> list[CustomerAccessDto]:
        """List non-seed customers and derive expiry from server time."""

        statement = (
            select(Customer, CustomerAccessLink)
            .join(CustomerAccessLink, CustomerAccessLink.customer_id == Customer.id)
            .where(Customer.is_development_seed.is_(False))
            .order_by(Customer.created_at.desc(), Customer.id.desc())
        )
        normalized_search = search.strip()
        if normalized_search:
            statement = statement.where(
                func.lower(Customer.name).contains(normalized_search.lower())
            )
        rows = (await session.execute(statement)).all()
        items = [self._to_dto(customer, access_link) for customer, access_link in rows]
        if status_filter != "all":
            items = [item for item in items if item.status == status_filter]
        return items

    async def create_customer(
        self,
        session: AsyncSession,
        *,
        name: str,
        validity_days: int,
        activate_immediately: bool,
        actor_id: str,
        trace_id: str,
    ) -> CustomerAccessDto:
        """Create one customer and one uniquely generated current link atomically."""

        normalized_name = name.strip()
        if not normalized_name or len(normalized_name) > 200:
            raise ValueError("Customer name is invalid")
        if validity_days not in {1, 3, 7}:
            raise ValueError("Customer validity is invalid")
        cipher = self._cipher()
        self._frontend_base_url()
        now = utc_now()
        customer = Customer(
            id=uuid4().hex,
            name=normalized_name,
            is_development_seed=False,
            access_state="active" if activate_immediately else "unstarted",
            initial_validity_days=validity_days,
            access_expires_at=(now + timedelta(days=validity_days))
            if activate_immediately
            else None,
            updated_at=now,
            created_at=now,
        )
        token = secrets.token_urlsafe(32)
        access_link = CustomerAccessLink(
            id=uuid4().hex,
            customer_id=customer.id,
            token_hash=self.auth.hash_access_token(token),
            token_ciphertext=cipher.encrypt(token.encode("utf-8")).decode("ascii"),
            token_masked=self._mask_token(token),
            created_at=now,
        )
        session.add_all((customer, access_link))
        await self.events.record_audit(
            session,
            action="customer.access.created",
            resource_type="customer",
            resource_id=customer.id,
            actor_id=actor_id,
            trace_id=trace_id,
            summary={
                "customer_name": normalized_name,
                "validity_days": validity_days,
                "activate_immediately": activate_immediately,
            },
        )
        return self._to_dto(customer, access_link)

    async def enable(
        self, session: AsyncSession, customer_id: str, *, actor_id: str, trace_id: str
    ) -> CustomerAccessDto:
        """Start the configured 1/3/7-day validity window for an unstarted customer."""

        customer, link = await self._get_customer_with_link(session, customer_id)
        self._require_state(customer, "unstarted")
        now = utc_now()
        customer.access_state = "active"
        customer.access_expires_at = now + timedelta(days=customer.initial_validity_days)
        customer.updated_at = now
        await self._record_state_change(session, customer, actor_id, trace_id, "enabled")
        return self._to_dto(customer, link)

    async def update_expiration(
        self,
        session: AsyncSession,
        customer_id: str,
        *,
        access_expires_at: datetime,
        actor_id: str,
        trace_id: str,
    ) -> CustomerAccessDto:
        """Change only a live active/stopped customer's future expiry."""

        customer, link = await self._get_customer_with_link(session, customer_id)
        # Expired rows retain their persisted intent (active or stopped). That
        # intent determines whether a future expiry immediately reopens access.
        if customer.access_state not in {"active", "stopped"}:
            raise CustomerAccessStateError(
                "invalid_customer_state", "Only active or stopped access can be edited"
            )
        if access_expires_at.tzinfo is None:
            raise InvalidAccessExpirationError("Expiration must include a timezone")
        normalized_expiration = as_utc(access_expires_at)
        if normalized_expiration <= utc_now():
            raise InvalidAccessExpirationError("Expiration must be in the future")
        was_expired = self.derive_status(customer) == "expired"
        customer.access_expires_at = normalized_expiration
        now = utc_now()
        customer.updated_at = now
        if was_expired and customer.access_state == "active":
            await self._lark.resume_customer(session, customer.id, now=now)
        await self._record_state_change(session, customer, actor_id, trace_id, "expiration_updated")
        return self._to_dto(customer, link)

    async def stop(
        self, session: AsyncSession, customer_id: str, *, actor_id: str, trace_id: str
    ) -> CustomerAccessDto:
        """Stop active access, preserve expiry, and revoke every existing session."""

        customer, link = await self._get_customer_with_link(session, customer_id)
        self._require_state(customer, "active")
        now = utc_now()
        customer.access_state = "stopped"
        customer.updated_at = now
        await self.auth.revoke_customer_sessions(session, customer.id)
        await self._lark.pause_customer(session, customer.id, now=now, reason="customer_stopped")
        await self._record_state_change(session, customer, actor_id, trace_id, "stopped")
        return self._to_dto(customer, link)

    async def resume(
        self, session: AsyncSession, customer_id: str, *, actor_id: str, trace_id: str
    ) -> CustomerAccessDto:
        """Resume stopped access without extending its original expiration."""

        customer, link = await self._get_customer_with_link(session, customer_id)
        self._require_state(customer, "stopped")
        customer.access_state = "active"
        now = utc_now()
        customer.updated_at = now
        await self._lark.resume_customer(session, customer.id, now=now)
        await self._record_state_change(session, customer, actor_id, trace_id, "resumed")
        return self._to_dto(customer, link)

    async def copy_access_url(
        self, session: AsyncSession, customer_id: str, *, actor_id: str, trace_id: str
    ) -> str:
        """Decrypt the current token only long enough to construct the copied URL."""

        customer, link = await self._get_customer_with_link(session, customer_id)
        try:
            token = self._cipher().decrypt(link.token_ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, UnicodeError) as error:
            raise AuthConfigurationError("Customer access token cannot be decrypted") from error
        await self.events.record_audit(
            session,
            action="customer.access.copied",
            resource_type="customer_access_link",
            resource_id=link.id,
            actor_id=actor_id,
            trace_id=trace_id,
            summary={"customer_id": customer.id, "result": "copied"},
        )
        return f"{self._frontend_base_url()}/access?token={token}"

    async def verify_access_token(
        self, session: AsyncSession, token: str, *, trace_id: str
    ) -> tuple[Customer, CustomerAccessLink]:
        """Validate an access token and its derived customer lifecycle state."""

        token_hash = self.auth.hash_access_token(token)
        link = await session.scalar(
            select(CustomerAccessLink).where(CustomerAccessLink.token_hash == token_hash)
        )
        if link is None or not hmac.compare_digest(link.token_hash, token_hash):
            await self.events.record_audit(
                session,
                action="customer.auth.verify_failed",
                resource_type="customer_access_link",
                resource_id="unknown",
                actor_id=None,
                trace_id=trace_id,
                summary={"reason": "invalid_access_link"},
            )
            raise InvalidAccessLinkError
        customer = await session.get(Customer, link.customer_id)
        if customer is None or customer.is_development_seed:
            raise InvalidAccessLinkError
        customer_status = self.derive_status(customer)
        if customer_status != "active":
            error_code = {
                "unstarted": "access_not_started",
                "stopped": "access_stopped",
                "expired": "access_expired",
            }[customer_status]
            await self.events.record_audit(
                session,
                action="customer.auth.verify_failed",
                resource_type="customer_access_link",
                resource_id=link.id,
                actor_id=customer.id,
                trace_id=trace_id,
                summary={"reason": error_code},
            )
            raise CustomerAccessStateError(error_code, "Customer access is unavailable")
        return customer, link

    def derive_status(self, customer: Customer) -> CustomerAccessStatus:
        """Compute terminal expiry from server time without relying on a scheduled job."""

        if customer.access_state == "unstarted":
            return "unstarted"
        if customer.access_expires_at is None or as_utc(customer.access_expires_at) <= utc_now():
            return "expired"
        return "stopped" if customer.access_state == "stopped" else "active"

    async def _get_customer_with_link(
        self, session: AsyncSession, customer_id: str
    ) -> tuple[Customer, CustomerAccessLink]:
        row = (
            await session.execute(
                select(Customer, CustomerAccessLink)
                .join(CustomerAccessLink, CustomerAccessLink.customer_id == Customer.id)
                .where(Customer.id == customer_id, Customer.is_development_seed.is_(False))
            )
        ).one_or_none()
        if row is None:
            raise CustomerAccessNotFoundError
        return row[0], row[1]

    def _require_state(self, customer: Customer, expected: CustomerAccessStatus) -> None:
        if self.derive_status(customer) != expected:
            raise CustomerAccessStateError(
                "invalid_customer_state", f"Customer access must be {expected}"
            )

    async def _record_state_change(
        self,
        session: AsyncSession,
        customer: Customer,
        actor_id: str,
        trace_id: str,
        action: str,
    ) -> None:
        await self.events.record_audit(
            session,
            action=f"customer.access.{action}",
            resource_type="customer",
            resource_id=customer.id,
            actor_id=actor_id,
            trace_id=trace_id,
            summary={"state": self.derive_status(customer)},
        )

    def _to_dto(self, customer: Customer, access_link: CustomerAccessLink) -> CustomerAccessDto:
        state = self.derive_status(customer)
        expiration = (
            None
            if state == "unstarted" or customer.access_expires_at is None
            else as_utc(customer.access_expires_at)
        )
        return CustomerAccessDto(
            id=customer.id,
            name=customer.name,
            masked_access_url=(
                f"{self._frontend_base_url()}/access?token={access_link.token_masked}"
            ),
            status=state,
            access_expires_at=expiration,
        )

    def _cipher(self) -> Fernet:
        key = self.settings.customer_access_token_encryption_key or ""
        try:
            return Fernet(key.encode("ascii"))
        except (ValueError, TypeError) as error:
            raise AuthConfigurationError(
                "Customer access token encryption configuration is unavailable"
            ) from error

    def _frontend_base_url(self) -> str:
        value = (self.settings.customer_frontend_base_url or "").strip().rstrip("/")
        parsed = urlsplit(value)
        is_development = self.settings.app_env.strip().lower() == "development"
        loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        is_preproduction = self.settings.app_env.strip().lower() == "preproduction"
        valid_scheme = parsed.scheme == "https" or (
            (is_development or is_preproduction) and parsed.scheme == "http" and loopback
        )
        if (
            not value
            or not valid_scheme
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise AuthConfigurationError("Customer frontend base URL is unavailable")
        return value

    @staticmethod
    def _mask_token(token: str) -> str:
        return f"{token[:3]}••••••••{token[-3:]}"
