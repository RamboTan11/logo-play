"""Repair T-027 source-image foreign keys with append-only SQLite rebuilds."""

from collections.abc import Iterable

from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

VERSION = "0018_t027_source_image_foreign_keys"

_TABLES: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    (
        "asset_records",
        "owner_customer_id",
        (
            "asset_id",
            "purpose",
            "storage_backend",
            "storage_key",
            "content_hash",
            "media_type",
            "size",
            "original_filename",
            "source_resource_type",
            "source_resource_id",
            "owner_customer_id",
            "created_at",
        ),
        """
        CREATE TABLE {temporary} (
            asset_id VARCHAR(64) NOT NULL PRIMARY KEY,
            purpose VARCHAR(80) NOT NULL,
            storage_backend VARCHAR(40) NOT NULL,
            storage_key VARCHAR(255) NOT NULL,
            content_hash VARCHAR(64) NOT NULL,
            media_type VARCHAR(100) NOT NULL,
            size INTEGER NOT NULL,
            original_filename VARCHAR(255),
            source_resource_type VARCHAR(80),
            source_resource_id VARCHAR(64),
            owner_customer_id VARCHAR(64),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            UNIQUE (storage_key),
            FOREIGN KEY (owner_customer_id) REFERENCES customers (id) ON DELETE RESTRICT
        )
        """,
    ),
    (
        "generation_requests",
        "source_image_asset_id",
        (
            "id",
            "customer_id",
            "domain",
            "policy_version_id",
            "model_connection_id",
            "model_connection_version",
            "target_count",
            "status",
            "error_code",
            "failure_summary_json",
            "created_at",
            "updated_at",
            "domain_label",
            "domain_suffix",
            "source_image_asset_id",
            "user_reference_requirement_raw",
            "user_reference_requirement_normalized",
            "generation_mode",
        ),
        """
        CREATE TABLE {temporary} (
            id VARCHAR(64) NOT NULL PRIMARY KEY,
            customer_id VARCHAR(64) NOT NULL,
            domain VARCHAR(255) NOT NULL,
            policy_version_id VARCHAR(64) NOT NULL,
            model_connection_id VARCHAR(64) NOT NULL,
            model_connection_version INTEGER NOT NULL,
            target_count INTEGER NOT NULL,
            status VARCHAR(24) NOT NULL,
            error_code VARCHAR(80),
            failure_summary_json TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            domain_label VARCHAR(250) NOT NULL DEFAULT '',
            domain_suffix VARCHAR(5) NOT NULL DEFAULT '.com',
            source_image_asset_id VARCHAR(64),
            user_reference_requirement_raw TEXT,
            user_reference_requirement_normalized TEXT NOT NULL DEFAULT '无额外参考要求',
            generation_mode VARCHAR(32) NOT NULL DEFAULT 'text_generation',
            FOREIGN KEY (customer_id) REFERENCES customers (id) ON DELETE RESTRICT,
            FOREIGN KEY (policy_version_id) REFERENCES batch_generation_policy_versions (id) ON DELETE RESTRICT,
            FOREIGN KEY (model_connection_id) REFERENCES model_connections (id) ON DELETE RESTRICT,
            FOREIGN KEY (source_image_asset_id) REFERENCES asset_records (asset_id) ON DELETE RESTRICT
        )
        """,
    ),
    (
        "generation_candidate_jobs",
        "source_image_asset_id",
        (
            "id",
            "request_id",
            "ordinal",
            "style_id",
            "template_id",
            "reference_image_asset_id",
            "status",
            "attempt_count",
            "run_snapshot_json",
            "result_asset_id",
            "error_code",
            "created_at",
            "updated_at",
            "provider_task_id",
            "provider_submission_state",
            "source_image_asset_id",
        ),
        """
        CREATE TABLE {temporary} (
            id VARCHAR(64) NOT NULL PRIMARY KEY,
            request_id VARCHAR(64) NOT NULL,
            ordinal INTEGER NOT NULL,
            style_id VARCHAR(128) NOT NULL,
            template_id VARCHAR(128) NOT NULL,
            reference_image_asset_id VARCHAR(64),
            status VARCHAR(24) NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            run_snapshot_json TEXT NOT NULL,
            result_asset_id VARCHAR(64),
            error_code VARCHAR(80),
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            provider_task_id VARCHAR(255),
            provider_submission_state VARCHAR(24),
            source_image_asset_id VARCHAR(64),
            FOREIGN KEY (request_id) REFERENCES generation_requests (id) ON DELETE RESTRICT,
            FOREIGN KEY (reference_image_asset_id) REFERENCES asset_records (asset_id) ON DELETE RESTRICT,
            FOREIGN KEY (result_asset_id) REFERENCES asset_records (asset_id) ON DELETE RESTRICT,
            FOREIGN KEY (source_image_asset_id) REFERENCES asset_records (asset_id) ON DELETE RESTRICT
        )
        """,
    ),
)


def _foreign_key_exists(connection: Connection, table: str, column: str, target: str) -> bool:
    rows = connection.execute(text(f"PRAGMA foreign_key_list('{table}')")).fetchall()
    return any(row[3] == column and row[2] == target for row in rows)


def _index_sql(connection: Connection, table: str) -> list[str]:
    rows = connection.execute(
        text(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'index' AND tbl_name = :table AND sql IS NOT NULL"
        ),
        {"table": table},
    ).fetchall()
    return [str(row[0]) for row in rows]


def _rebuild_table(
    connection: Connection,
    table: str,
    columns: Iterable[str],
    create_sql: str,
) -> None:
    temporary = f"{table}_v0018"
    column_list = ", ".join(columns)
    indexes = _index_sql(connection, table)
    connection.execute(text(create_sql.format(temporary=temporary)))
    connection.execute(
        text(
            f"INSERT INTO {temporary} ({column_list}) "
            f"SELECT {column_list} FROM {table}"
        )
    )
    connection.execute(text(f"DROP TABLE {table}"))
    connection.execute(text(f"ALTER TABLE {temporary} RENAME TO {table}"))
    for index in indexes:
        connection.exec_driver_sql(index)


def _upgrade(connection: Connection) -> None:
    connection.execute(text("PRAGMA foreign_keys = OFF"))
    try:
        for table, column, columns, create_sql in _TABLES:
            inspector = inspect(connection)
            if not inspector.has_table(table):
                continue
            existing_columns = {column["name"] for column in inspector.get_columns(table)}
            if not set(columns) <= existing_columns:
                continue
            target = "customers" if table == "asset_records" else "asset_records"
            if not inspector.has_table(target):
                continue
            if not _foreign_key_exists(connection, table, column, target):
                _rebuild_table(connection, table, columns, create_sql)
    finally:
        connection.execute(text("PRAGMA foreign_keys = ON"))


async def upgrade(connection: AsyncConnection) -> None:
    await connection.run_sync(_upgrade)
