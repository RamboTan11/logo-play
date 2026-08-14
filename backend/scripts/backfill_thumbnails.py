"""Create missing previews for existing generated and delivered images.

This maintenance command is intentionally sequential. It writes only missing
WebP sidecars and never changes database rows or original assets.
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.config import load_settings
from src.db.models import AssetRecord
from src.db.session import create_database_runtime
from src.services.asset_service import (
    GENERATED_LOGO_PURPOSE,
    TASK_DELIVERY_IMAGE_PURPOSE,
    LocalFallbackAssetStorage,
)


async def main() -> None:
    """Backfill only missing previews without touching application state."""

    settings = load_settings()
    runtime = create_database_runtime(settings)
    storage = LocalFallbackAssetStorage(settings.asset_root)
    created = skipped = unavailable = 0
    try:
        async with runtime.session_factory() as session:
            storage_keys = (
                await session.scalars(
                    select(AssetRecord.storage_key).where(
                        AssetRecord.purpose.in_(
                            [GENERATED_LOGO_PURPOSE, TASK_DELIVERY_IMAGE_PURPOSE]
                        )
                    )
                )
            ).all()
        for storage_key in storage_keys:
            if storage.has_thumbnail(storage_key):
                skipped += 1
                continue
            try:
                content = storage.read(storage_key)
            except OSError:
                unavailable += 1
                continue
            if storage.write_thumbnail(storage_key, content):
                created += 1
            else:
                unavailable += 1
    finally:
        await runtime.dispose()
    print(
        f"Thumbnail backfill complete: created={created}, "
        f"already_present={skipped}, unavailable={unavailable}"
    )


if __name__ == "__main__":
    asyncio.run(main())
