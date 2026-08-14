"""Immutable local-fallback asset storage for internal server use."""

import warnings
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from threading import Lock
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models import AssetRecord
from src.db.session import resolve_backend_path
from src.services.event_service import EventService

REFERENCE_IMAGE_PURPOSE = "model_strategy_reference"
CUSTOMER_GENERATION_SOURCE_PURPOSE = "customer_generation_source"
GENERATED_LOGO_PURPOSE = "generated_logo"
TASK_DELIVERY_IMAGE_PURPOSE = "task_delivery_image"
LOCAL_FALLBACK = "local_fallback"
SOURCE_IMAGE_MEDIA_TYPES = {"image/png", "image/jpeg", "image/webp"}
_SOURCE_IMAGE_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}
THUMBNAIL_MEDIA_TYPE = "image/webp"
THUMBNAIL_MAX_EDGE = 640


@dataclass(frozen=True, slots=True)
class StoredAsset:
    """The immutable identifiers returned from an internal asset write."""

    asset_id: str
    storage_key: str
    content_hash: str


class LocalFallbackAssetStorage:
    """Store generated keys beneath the configured server-owned asset root."""

    _thumbnail_locks: dict[str, Lock] = {}
    _thumbnail_locks_guard = Lock()

    def __init__(self, configured_root: str) -> None:
        self.root: Path = resolve_backend_path(configured_root)
        self.root.mkdir(parents=True, exist_ok=True)

    def write(self, content: bytes, media_type: str) -> StoredAsset:
        """Write server-provided bytes under a new opaque storage key."""

        if not content:
            raise ValueError("Asset content must not be empty")
        suffix = _suffix_for_media_type(media_type)
        asset_id = uuid4().hex
        storage_key = f"assets/{uuid4().hex}{suffix}"
        target = self._path_for_key(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return StoredAsset(asset_id, storage_key, sha256(content).hexdigest())

    def read(self, storage_key: str) -> bytes:
        """Read an asset only after proving its generated key stays under the root."""

        return self._path_for_key(storage_key).read_bytes()

    def has_thumbnail(self, storage_key: str) -> bool:
        """Return whether an asset already has its persisted WebP preview."""

        return self._thumbnail_path(storage_key).is_file()

    def read_thumbnail(self, storage_key: str, original: bytes) -> bytes:
        """Return a persisted WebP preview, deriving it locally on first request."""

        target = self._thumbnail_path(storage_key)
        if target.is_file():
            return target.read_bytes()
        lock = self._thumbnail_lock(storage_key)
        with lock:
            if target.is_file():
                return target.read_bytes()
            thumbnail = self._build_thumbnail(original)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(thumbnail)
            return thumbnail

    def write_thumbnail(self, storage_key: str, original: bytes) -> bool:
        """Best-effort thumbnail generation that never blocks an asset write."""

        target = self._thumbnail_path(storage_key)
        if target.is_file():
            return True
        lock = self._thumbnail_lock(storage_key)
        with lock:
            if target.is_file():
                return True
            try:
                thumbnail = self._build_thumbnail(original)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(thumbnail)
            except (OSError, UnidentifiedImageError, ValueError):
                return False
        return True

    def delete(self, storage_key: str) -> None:
        """Remove an uncommitted staged file after a rejected state transition."""

        try:
            self._path_for_key(storage_key).unlink(missing_ok=True)
            self._thumbnail_path(storage_key).unlink(missing_ok=True)
        except OSError:
            return

    def _thumbnail_path(self, storage_key: str) -> Path:
        return self._path_for_key(f"{storage_key}.thumb.webp")

    @staticmethod
    def _build_thumbnail(original: bytes) -> bytes:
        try:
            with Image.open(BytesIO(original)) as image:
                image.thumbnail((THUMBNAIL_MAX_EDGE, THUMBNAIL_MAX_EDGE), Image.Resampling.LANCZOS)
                output = BytesIO()
                image.save(output, format="WEBP", quality=80, method=6)
                return output.getvalue()
        except (OSError, UnidentifiedImageError, ValueError) as error:
            raise ValueError("Unable to create image thumbnail") from error

    @classmethod
    def _thumbnail_lock(cls, storage_key: str) -> Lock:
        with cls._thumbnail_locks_guard:
            return cls._thumbnail_locks.setdefault(storage_key, Lock())

    def _path_for_key(self, storage_key: str) -> Path:
        candidate: Path = Path(self.root / storage_key).resolve()
        try:
            candidate.relative_to(self.root.resolve())
        except ValueError as error:
            raise ValueError("Invalid storage key") from error
        return candidate


class AssetService:
    """Create immutable asset records while keeping file paths internal."""

    def __init__(self, storage: LocalFallbackAssetStorage, events: EventService) -> None:
        self._storage = storage
        self._events = events

    async def create_reference_image(
        self,
        session: AsyncSession,
        *,
        content: bytes,
        media_type: str,
        actor_id: str,
        trace_id: str,
        source_resource_type: str | None = None,
        source_resource_id: str | None = None,
        original_filename: str | None = None,
        owner_customer_id: str | None = None,
    ) -> AssetRecord:
        """Create a new reference-image version without modifying prior assets."""

        stored = self._storage.write(content, media_type)
        record = AssetRecord(
            asset_id=stored.asset_id,
            purpose=REFERENCE_IMAGE_PURPOSE,
            storage_backend=LOCAL_FALLBACK,
            storage_key=stored.storage_key,
            content_hash=stored.content_hash,
            media_type=media_type,
            size=len(content),
            original_filename=original_filename,
            source_resource_type=source_resource_type,
            source_resource_id=source_resource_id,
            owner_customer_id=owner_customer_id,
        )
        session.add(record)
        await self._events.record_audit(
            session,
            action="asset.created",
            resource_type="asset",
            resource_id=record.asset_id,
            actor_id=actor_id,
            trace_id=trace_id,
            summary={"purpose": record.purpose, "storage_backend": LOCAL_FALLBACK},
        )
        return record

    async def create_customer_generation_source(
        self,
        session: AsyncSession,
        *,
        content: bytes,
        media_type: str,
        actor_id: str,
        trace_id: str,
        original_filename: str | None = None,
    ) -> AssetRecord:
        """Persist one immutable source image owned by the authenticated customer."""

        if media_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise ValueError("Customer source image must be PNG, JPEG, or WebP")
        stored = self._storage.write(content, media_type)
        record = AssetRecord(
            asset_id=stored.asset_id,
            purpose=CUSTOMER_GENERATION_SOURCE_PURPOSE,
            storage_backend=LOCAL_FALLBACK,
            storage_key=stored.storage_key,
            content_hash=stored.content_hash,
            media_type=media_type,
            size=len(content),
            original_filename=original_filename,
            owner_customer_id=actor_id,
        )
        session.add(record)
        await self._events.record_audit(
            session,
            action="customer_generation_source.created",
            resource_type="asset",
            resource_id=record.asset_id,
            actor_id=actor_id,
            trace_id=trace_id,
            summary={"purpose": CUSTOMER_GENERATION_SOURCE_PURPOSE, "storage_backend": LOCAL_FALLBACK},
        )
        return record

    async def create_generated_logo(
        self,
        session: AsyncSession,
        *,
        content: bytes,
        media_type: str = "image/jpeg",
        actor_id: str,
        trace_id: str,
        source_resource_id: str,
        source_resource_type: str = "generation_candidate_job",
    ) -> AssetRecord:
        """Persist one validated native PNG or JPEG as an immutable business result."""

        if media_type not in {"image/png", "image/jpeg"}:
            raise ValueError("Generated Logo must be PNG or JPEG")
        stored = self._storage.write(content, media_type)
        # A thumbnail is an optimization only. A malformed provider response
        # must not turn a successful original-image write into a failed job.
        self._storage.write_thumbnail(stored.storage_key, content)
        record = AssetRecord(
            asset_id=stored.asset_id,
            purpose=GENERATED_LOGO_PURPOSE,
            storage_backend=LOCAL_FALLBACK,
            storage_key=stored.storage_key,
            content_hash=stored.content_hash,
            media_type=media_type,
            size=len(content),
            source_resource_type=source_resource_type,
            source_resource_id=source_resource_id,
        )
        session.add(record)
        await self._events.record_audit(
            session,
            action="generated_logo.created",
            resource_type="asset",
            resource_id=record.asset_id,
            actor_id=actor_id,
            trace_id=trace_id,
            summary={"purpose": GENERATED_LOGO_PURPOSE, "storage_backend": LOCAL_FALLBACK},
        )
        return record

    async def read_generated_logo(
        self, session: AsyncSession, asset_id: str, *, thumbnail: bool = False
    ) -> tuple[AssetRecord, bytes]:
        record = await session.get(AssetRecord, asset_id)
        if record is None or record.purpose != GENERATED_LOGO_PURPOSE:
            raise LookupError("Generated Logo not found")
        try:
            content = self._storage.read(record.storage_key)
            return record, self._storage.read_thumbnail(record.storage_key, content) if thumbnail else content
        except OSError as error:
            raise LookupError("Generated Logo not found") from error

    async def read_task_delivery_image(
        self, session: AsyncSession, asset_id: str, *, thumbnail: bool = False
    ) -> tuple[AssetRecord, bytes]:
        """Read one protected delivery image without exposing a storage location."""

        record = await session.get(AssetRecord, asset_id)
        if record is None or record.purpose != TASK_DELIVERY_IMAGE_PURPOSE:
            raise LookupError("Task delivery image not found")
        try:
            content = self._storage.read(record.storage_key)
            return record, self._storage.read_thumbnail(record.storage_key, content) if thumbnail else content
        except OSError as error:
            raise LookupError("Task delivery image not found") from error

    async def list_reference_images(
        self, session: AsyncSession, asset_ids: list[str]
    ) -> list[AssetRecord]:
        """Return only requested strategy-reference assets in requested order."""

        ordered_ids = list(dict.fromkeys(asset_id for asset_id in asset_ids if asset_id))
        if not ordered_ids:
            return []
        records = (
            await session.scalars(
                select(AssetRecord).where(
                    AssetRecord.asset_id.in_(ordered_ids),
                    AssetRecord.purpose == REFERENCE_IMAGE_PURPOSE,
                )
            )
        ).all()
        by_id = {record.asset_id: record for record in records}
        return [by_id[asset_id] for asset_id in ordered_ids if asset_id in by_id]

    async def read_reference_image(
        self, session: AsyncSession, asset_id: str
    ) -> tuple[AssetRecord, bytes]:
        """Read a strategy reference image without exposing its storage location."""

        record = await session.get(AssetRecord, asset_id)
        if record is None or record.purpose != REFERENCE_IMAGE_PURPOSE:
            raise LookupError("Reference image not found")
        try:
            return record, self._storage.read(record.storage_key)
        except OSError as error:
            raise LookupError("Reference image not found") from error

    async def read_customer_generation_source(
        self, session: AsyncSession, asset_id: str, customer_id: str
    ) -> tuple[AssetRecord, bytes]:
        """Read a source image only for its owning customer."""

        record = await session.get(AssetRecord, asset_id)
        if (
            record is None
            or record.purpose != CUSTOMER_GENERATION_SOURCE_PURPOSE
            or record.owner_customer_id != customer_id
        ):
            raise LookupError("Customer source image not found")
        try:
            return record, self._storage.read(record.storage_key)
        except OSError as error:
            raise LookupError("Customer source image not found") from error


def is_valid_source_image(content: bytes, media_type: str) -> bool:
    """Fully decode one bounded PNG, JPEG, or WebP without retaining image pixels."""

    expected_format = _SOURCE_IMAGE_FORMATS.get(media_type)
    if not content or expected_format is None:
        return False
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                if image.format != expected_format:
                    return False
                image.verify()
            with Image.open(BytesIO(content)) as image:
                for frame_index in range(getattr(image, "n_frames", 1)):
                    image.seek(frame_index)
                    image.load()
                    if image.width < 1 or image.height < 1:
                        return False
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        SyntaxError,
        UnidentifiedImageError,
        ValueError,
    ):
        return False
    return True


def _suffix_for_media_type(media_type: str) -> str:
    """Allow only image media types accepted by the strategy reference workflow."""

    suffixes = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    try:
        return suffixes[media_type.lower()]
    except KeyError as error:
        raise ValueError("Unsupported asset media type") from error
