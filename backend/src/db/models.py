"""Persistent models for the shared infrastructure baseline."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Project ORM base, kept separate from PyCore's example models."""


class SchemaMigration(Base):
    """An applied append-only schema migration."""

    __tablename__ = "schema_migrations"

    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Customer(Base):
    """A customer identity and its access lifecycle state."""

    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_development_seed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    access_state: Mapped[str] = mapped_column(String(24), default="unstarted", nullable=False)
    initial_validity_days: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SharedAdministrator(Base):
    """The single shared administrator account used during the V1 phase."""

    __tablename__ = "shared_administrators"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CustomerAccessLink(Base):
    """One current bearer access link for a non-development customer."""

    __tablename__ = "customer_access_links"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    token_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    token_masked: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AdminSession(Base):
    """A server-side shared-administrator browser session."""

    __tablename__ = "admin_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    administrator_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("shared_administrators.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CustomerSession(Base):
    """A server-side customer session bound to its issuing access link."""

    __tablename__ = "customer_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    customer_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_access_link_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("customer_access_links.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ModelConnection(Base):
    """Non-secret connection metadata reserved for model strategy tasks."""

    __tablename__ = "model_connections"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    api_url: Mapped[str | None] = mapped_column(String(500))
    region_or_workspace: Mapped[str | None] = mapped_column(String(128))
    connection_status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    verified_capabilities_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    max_input_images: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ModelConnectionSecret(Base):
    """Authenticated-encrypted API Key for exactly one model connection."""

    __tablename__ = "model_connection_secrets"

    connection_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("model_connections.id", ondelete="CASCADE"), primary_key=True
    )
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    encryption_key_version: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AssetRecord(Base):
    """An immutable server-managed asset record."""

    __tablename__ = "asset_records"

    asset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(80), nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(40), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    source_resource_type: Mapped[str | None] = mapped_column(String(80))
    source_resource_id: Mapped[str | None] = mapped_column(String(64))
    owner_customer_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("customers.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BatchGenerationPolicyVersion(Base):
    """One immutable published snapshot for the batch image-to-image scene."""

    __tablename__ = "batch_generation_policy_versions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    model_connection_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("model_connections.id", ondelete="RESTRICT"), nullable=False
    )
    model_connection_version: Mapped[int] = mapped_column(Integer, nullable=False)
    styles_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BatchGenerationPolicyState(Base):
    """The active pointer plus the separately persisted editor draft."""

    __tablename__ = "batch_generation_policy_state"

    scene: Mapped[str] = mapped_column(String(64), primary_key=True)
    active_version_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("batch_generation_policy_versions.id", ondelete="RESTRICT"),
    )
    draft_payload_json: Mapped[str | None] = mapped_column(Text)
    draft_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BatchGenerationStyleRotationCursor(Base):
    """The next complete-template offset for one style in one immutable policy version."""

    __tablename__ = "batch_generation_style_rotation_cursors"

    policy_version_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("batch_generation_policy_versions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    style_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    next_template_offset: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SingleImageEditPolicyVersion(Base):
    """One immutable published snapshot for the single-image editing scene."""

    __tablename__ = "single_image_edit_policy_versions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    model_connection_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("model_connections.id", ondelete="RESTRICT"), nullable=False
    )
    model_connection_version: Mapped[int] = mapped_column(Integer, nullable=False)
    positive_content: Mapped[str] = mapped_column(Text, nullable=False)
    user_description_template: Mapped[str] = mapped_column(Text, nullable=False)
    negative_avoidance: Mapped[str] = mapped_column(Text, nullable=False)
    compiler_version: Mapped[str] = mapped_column(
        String(64),
        default="logo-prompt-compiler-v3",
        server_default=text("'logo-prompt-compiler-v3'"),
        nullable=False,
    )
    rule_set_version: Mapped[str] = mapped_column(
        String(64), default="legacy", server_default=text("'legacy'"), nullable=False
    )
    rule_blocks_json: Mapped[str] = mapped_column(
        Text, default="[]", server_default=text("'[]'"), nullable=False
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SingleImageEditPolicyState(Base):
    """The active pointer for append-only single-image policy versions."""

    __tablename__ = "single_image_edit_policy_state"

    scene: Mapped[str] = mapped_column(String(64), primary_key=True)
    active_version_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("single_image_edit_policy_versions.id", ondelete="RESTRICT"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DesignTask(Base):
    """A customer design task with an immutable-at-adoption context snapshot."""

    __tablename__ = "design_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    adoption_suggestion: Mapped[str | None] = mapped_column(Text)
    customer_feedback: Mapped[str | None] = mapped_column(Text)
    rating: Mapped[int | None] = mapped_column(Integer)
    adopted_logo_version_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("logo_versions.id", ondelete="RESTRICT")
    )
    adopted_asset_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("asset_records.asset_id", ondelete="RESTRICT")
    )
    initial_logo_version_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("logo_versions.id", ondelete="RESTRICT")
    )
    initial_asset_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("asset_records.asset_id", ondelete="RESTRICT")
    )
    delivery_asset_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("asset_records.asset_id", ondelete="RESTRICT")
    )
    ai_edit_inputs_json: Mapped[str] = mapped_column(
        Text, default="[]", server_default=text("'[]'"), nullable=False
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SavedLogo(Base):
    """One customer-owned saved Logo version; saving never creates a task."""

    __tablename__ = "saved_logos"
    __table_args__ = (
        UniqueConstraint("customer_id", "logo_version_id", name="uq_saved_logos_customer_version"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    logo_version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("logo_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class EndpointIdempotencyRecord(Base):
    """A replayable response isolated by customer, endpoint, and caller key."""

    __tablename__ = "endpoint_idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "customer_id", "endpoint", "idempotency_key", name="uq_endpoint_idempotency_scope"
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    endpoint: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GenerationRequest(Base):
    """One immutable customer batch request and its terminal status."""

    __tablename__ = "generation_requests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    domain_label: Mapped[str] = mapped_column(String(250), nullable=False)
    domain_suffix: Mapped[str] = mapped_column(String(5), nullable=False)
    source_image_asset_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("asset_records.asset_id", ondelete="RESTRICT")
    )
    user_reference_requirement_raw: Mapped[str | None] = mapped_column(Text)
    user_reference_requirement_normalized: Mapped[str] = mapped_column(
        Text, default="无额外参考要求", server_default=text("'无额外参考要求'"), nullable=False
    )
    generation_mode: Mapped[str] = mapped_column(
        String(32), default="text_generation", server_default=text("'text_generation'"), nullable=False
    )
    selected_style_ids_json: Mapped[str] = mapped_column(
        Text, default="[]", server_default=text("'[]'"), nullable=False
    )
    style_allocation_json: Mapped[str] = mapped_column(
        Text, default="{}", server_default=text("'{}'"), nullable=False
    )
    policy_version_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("batch_generation_policy_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    model_connection_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("model_connections.id", ondelete="RESTRICT"), nullable=False
    )
    model_connection_version: Mapped[int] = mapped_column(Integer, nullable=False)
    target_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    error_code: Mapped[str | None] = mapped_column(String(80))
    failure_summary_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GenerationCandidateJob(Base):
    """One provider request with an immutable strategy and prompt snapshot."""

    __tablename__ = "generation_candidate_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("generation_requests.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    style_id: Mapped[str] = mapped_column(String(128), nullable=False)
    template_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reference_image_asset_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("asset_records.asset_id", ondelete="RESTRICT"), nullable=True
    )
    source_image_asset_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("asset_records.asset_id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    run_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    provider_task_id: Mapped[str | None] = mapped_column(String(255))
    provider_submission_state: Mapped[str | None] = mapped_column(String(24))
    result_asset_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("asset_records.asset_id", ondelete="RESTRICT")
    )
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SingleImageEditRequest(Base):
    """One recoverable single-image edit run with an immutable input snapshot."""

    __tablename__ = "single_image_edit_requests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    root_logo_version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("logo_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_logo_version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("logo_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    policy_version_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("single_image_edit_policy_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    model_connection_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("model_connections.id", ondelete="RESTRICT"), nullable=False
    )
    model_connection_version: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    edit_instruction: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    run_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    provider_task_id: Mapped[str | None] = mapped_column(String(255))
    provider_submission_state: Mapped[str | None] = mapped_column(String(24))
    result_logo_version_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LogoVersion(Base):
    """An immutable customer-visible generated Logo image version."""

    __tablename__ = "logo_versions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    generation_request_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("generation_requests.id", ondelete="RESTRICT"), index=True
    )
    candidate_job_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("generation_candidate_jobs.id", ondelete="RESTRICT"), unique=True
    )
    single_edit_request_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("single_image_edit_requests.id", ondelete="RESTRICT"), unique=True
    )
    parent_logo_version_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("logo_versions.id", ondelete="RESTRICT"), index=True
    )
    root_logo_version_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("logo_versions.id", ondelete="RESTRICT"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    asset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("asset_records.asset_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class AuditEvent(Base):
    """A sanitized audit record for a stateful operation."""

    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64))
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    summary_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NotificationOutbox(Base):
    """A recoverable notification event committed with its business transaction."""

    __tablename__ = "notification_outbox"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(220), unique=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    claimed_by: Mapped[str | None] = mapped_column(String(64))
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LarkChannelConfig(Base):
    """Single fixed-group channel with encrypted routing credentials."""

    __tablename__ = "lark_channel_configs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    group_label: Mapped[str | None] = mapped_column(String(120))
    webhook_ciphertext: Mapped[str | None] = mapped_column(Text)
    signing_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    signing_secret_ciphertext: Mapped[str | None] = mapped_column(Text)
    last_test_status: Mapped[str | None] = mapped_column(String(24))
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LarkRecipient(Base):
    """One mention target whose Open ID is never persisted in plaintext."""

    __tablename__ = "lark_recipients"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(100))
    open_id_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    open_id_digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    open_id_masked: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LarkNotificationRule(Base):
    """Current editable rule; active tasks retain a separate immutable snapshot."""

    __tablename__ = "lark_notification_rules"

    event_type: Mapped[str] = mapped_column(String(100), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mention_all: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    recipient_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    threshold_hours: Mapped[int | None] = mapped_column(Integer)
    repeat_interval_hours: Mapped[int | None] = mapped_column(Integer)
    max_repeat_count: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LarkReminderSnapshot(Base):
    """Immutable timing and encrypted recipient snapshot for one task stage."""

    __tablename__ = "lark_reminder_snapshots"
    __table_args__ = (
        UniqueConstraint("task_id", "event_type", name="uq_lark_reminder_task_event"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("design_tasks.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    threshold_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    repeat_interval_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    max_repeat_count: Mapped[int] = mapped_column(Integer, nullable=False)
    mention_all: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    recipient_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    next_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    last_reminder_index: Mapped[int] = mapped_column(Integer, default=-1, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    stopped_reason: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LarkNotificationDelivery(Base):
    """Safe delivery state; provider responses and card bodies are not retained."""

    __tablename__ = "lark_notification_deliveries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    outbox_event_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("notification_outbox.event_id", ondelete="RESTRICT"), unique=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(64))
    reminder_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notification_mode: Mapped[str] = mapped_column(String(24), nullable=False)
    mention_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    error_category: Mapped[str | None] = mapped_column(String(80))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
