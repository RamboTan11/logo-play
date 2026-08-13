"""Initialize the local database without deleting existing records or assets."""

import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.config import load_settings
from src.db.migrations.runner import initialize_database
from src.db.session import create_database_runtime


async def main() -> None:
    """Apply missing migrations and ensure the development seed customer exists."""

    settings = load_settings()
    runtime = create_database_runtime(settings)
    try:
        await initialize_database(runtime, settings)
    finally:
        await runtime.dispose()


if __name__ == "__main__":
    asyncio.run(main())
