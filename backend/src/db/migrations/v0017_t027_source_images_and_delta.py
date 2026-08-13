"""Add T-027 source-image ownership, runtime facts, and delta-edit metadata."""

from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

VERSION = "0017_t027_source_images_and_delta"


def _add_column(connection: Connection, table: str, name: str, definition: str) -> None:
    columns = {column["name"] for column in inspect(connection).get_columns(table)}
    if name not in columns:
        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))


def _upgrade(connection: Connection) -> None:
    if inspect(connection).has_table("model_connections"):
        _add_column(connection, "model_connections", "max_input_images", "INTEGER")
    if inspect(connection).has_table("asset_records"):
        _add_column(connection, "asset_records", "owner_customer_id", "VARCHAR(64)")
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_asset_records_owner_customer_id "
                "ON asset_records (owner_customer_id)"
            )
        )
    if inspect(connection).has_table("generation_requests"):
        _add_column(connection, "generation_requests", "source_image_asset_id", "VARCHAR(64)")
        _add_column(connection, "generation_requests", "user_reference_requirement_raw", "TEXT")
        _add_column(
            connection,
            "generation_requests",
            "user_reference_requirement_normalized",
            "TEXT NOT NULL DEFAULT '无额外参考要求'",
        )
        _add_column(
            connection,
            "generation_requests",
            "generation_mode",
            "VARCHAR(32) NOT NULL DEFAULT 'text_generation'",
        )
    if inspect(connection).has_table("generation_candidate_jobs"):
        _add_column(connection, "generation_candidate_jobs", "source_image_asset_id", "VARCHAR(64)")
    if inspect(connection).has_table("single_image_edit_requests"):
        _add_column(connection, "single_image_edit_requests", "edit_instruction", "TEXT")
    if inspect(connection).has_table("single_image_edit_policy_versions"):
        _add_column(
            connection,
            "single_image_edit_policy_versions",
            "compiler_version",
            "VARCHAR(64) NOT NULL DEFAULT 'logo-prompt-compiler-v3'",
        )
        _add_column(
            connection,
            "single_image_edit_policy_versions",
            "rule_set_version",
            "VARCHAR(64) NOT NULL DEFAULT 'legacy'",
        )
        _add_column(
            connection,
            "single_image_edit_policy_versions",
            "rule_blocks_json",
            "TEXT NOT NULL DEFAULT '[]'",
        )


async def upgrade(connection: AsyncConnection) -> None:
    await connection.run_sync(_upgrade)
