"""Add structured domain input while preserving the complete business domain."""

from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

VERSION = "0014_generation_domain_parts"


def _upgrade(connection: Connection) -> None:
    inspector = inspect(connection)
    if not inspector.has_table("generation_requests"):
        return
    columns = {column["name"] for column in inspector.get_columns("generation_requests")}
    if "domain_label" not in columns:
        connection.execute(
            text(
                "ALTER TABLE generation_requests "
                "ADD COLUMN domain_label VARCHAR(250) NOT NULL DEFAULT ''"
            )
        )
    if "domain_suffix" not in columns:
        connection.execute(
            text(
                "ALTER TABLE generation_requests "
                "ADD COLUMN domain_suffix VARCHAR(5) NOT NULL DEFAULT '.com'"
            )
        )
    if "domain" not in columns:
        return
    connection.execute(
        text(
            "UPDATE generation_requests SET "
            "domain_label = CASE "
            "WHEN lower(domain) LIKE '%.game' THEN substr(domain, 1, length(domain) - 5) "
            "WHEN lower(domain) LIKE '%.com' OR lower(domain) LIKE '%.win' "
            "OR lower(domain) LIKE '%.app' "
            "THEN substr(domain, 1, length(domain) - 4) "
            "ELSE domain END, "
            "domain_suffix = CASE "
            "WHEN lower(domain) LIKE '%.game' THEN '.game' "
            "WHEN lower(domain) LIKE '%.win' THEN '.win' "
            "WHEN lower(domain) LIKE '%.app' THEN '.app' "
            "ELSE '.com' END "
            "WHERE domain_label = ''"
        )
    )


async def upgrade(connection: AsyncConnection) -> None:
    await connection.run_sync(_upgrade)
