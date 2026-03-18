"""initial schema

Revision ID: ae7c0da22271
Revises:
Create Date: 2026-03-18 16:19:49.387767

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "ae7c0da22271"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_created_at", "users", ["created_at"])

    op.create_table(
        "api_keys",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("key_prefix", sa.String(length=8), nullable=False),
        sa.Column("key_hash", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_api_keys_key_prefix", "api_keys", ["key_prefix"])
    op.create_index("ix_api_keys_owner_id", "api_keys", ["owner_id"])
    op.create_index("ix_api_keys_created_at", "api_keys", ["created_at"])
    op.create_index(
        "ix_api_keys_owner_created_at_desc",
        "api_keys",
        ["owner_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "sources",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("owner_id", "slug", name="uq_sources_owner_slug"),
    )
    op.create_index("ix_sources_owner_id", "sources", ["owner_id"])
    op.create_index("ix_sources_created_at", "sources", ["created_at"])
    op.create_index(
        "ix_sources_owner_created_at_desc",
        "sources",
        ["owner_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "endpoints",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("secret", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_endpoints_owner_id", "endpoints", ["owner_id"])
    op.create_index("ix_endpoints_created_at", "endpoints", ["created_at"])
    op.create_index(
        "ix_endpoints_owner_created_at_desc",
        "endpoints",
        ["owner_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "subscriptions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "endpoint_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("endpoints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "event_type_filter",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_subscriptions_owner_id", "subscriptions", ["owner_id"])
    op.create_index("ix_subscriptions_endpoint_id", "subscriptions", ["endpoint_id"])
    op.create_index("ix_subscriptions_source_id", "subscriptions", ["source_id"])
    op.create_index("ix_subscriptions_created_at", "subscriptions", ["created_at"])
    op.create_index(
        "ix_subscriptions_owner_created_at_desc",
        "subscriptions",
        ["owner_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "webhook_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "headers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("event_type", sa.String(length=255), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_webhook_events_source_id", "webhook_events", ["source_id"])
    op.create_index(
        "ix_webhook_events_idempotency_key",
        "webhook_events",
        ["idempotency_key"],
    )
    op.create_index("ix_webhook_events_event_type", "webhook_events", ["event_type"])
    op.create_index("ix_webhook_events_received_at", "webhook_events", ["received_at"])
    op.create_index("ix_webhook_events_created_at", "webhook_events", ["created_at"])
    op.create_index(
        "ix_webhook_events_created_at_desc",
        "webhook_events",
        [sa.text("created_at DESC")],
    )

    op.create_table(
        "delivery_attempts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("webhook_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "endpoint_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("endpoints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "delivering",
                "success",
                "failed",
                "retrying",
                "exhausted",
                name="deliverystatus",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("response_code", sa.SmallInteger(), nullable=True),
        sa.Column("response_body", sa.String(length=1000), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_delivery_attempts_event_id", "delivery_attempts", ["event_id"])
    op.create_index(
        "ix_delivery_attempts_endpoint_id",
        "delivery_attempts",
        ["endpoint_id"],
    )
    op.create_index("ix_delivery_attempts_status", "delivery_attempts", ["status"])
    op.create_index(
        "ix_delivery_attempts_attempted_at",
        "delivery_attempts",
        ["attempted_at"],
    )
    op.create_index(
        "ix_delivery_attempts_created_at",
        "delivery_attempts",
        ["created_at"],
    )
    op.create_index(
        "ix_delivery_attempts_endpoint_status",
        "delivery_attempts",
        ["endpoint_id", "status"],
    )
    op.create_index(
        "ix_delivery_attempts_created_at_desc",
        "delivery_attempts",
        [sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_delivery_attempts_created_at_desc",
        table_name="delivery_attempts",
    )
    op.drop_index(
        "ix_delivery_attempts_endpoint_status",
        table_name="delivery_attempts",
    )
    op.drop_index("ix_delivery_attempts_created_at", table_name="delivery_attempts")
    op.drop_index("ix_delivery_attempts_attempted_at", table_name="delivery_attempts")
    op.drop_index("ix_delivery_attempts_status", table_name="delivery_attempts")
    op.drop_index("ix_delivery_attempts_endpoint_id", table_name="delivery_attempts")
    op.drop_index("ix_delivery_attempts_event_id", table_name="delivery_attempts")
    op.drop_table("delivery_attempts")

    op.drop_index("ix_webhook_events_created_at_desc", table_name="webhook_events")
    op.drop_index("ix_webhook_events_created_at", table_name="webhook_events")
    op.drop_index("ix_webhook_events_received_at", table_name="webhook_events")
    op.drop_index("ix_webhook_events_event_type", table_name="webhook_events")
    op.drop_index("ix_webhook_events_idempotency_key", table_name="webhook_events")
    op.drop_index("ix_webhook_events_source_id", table_name="webhook_events")
    op.drop_table("webhook_events")

    op.drop_index("ix_subscriptions_owner_created_at_desc", table_name="subscriptions")
    op.drop_index("ix_subscriptions_created_at", table_name="subscriptions")
    op.drop_index("ix_subscriptions_source_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_endpoint_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_owner_id", table_name="subscriptions")
    op.drop_table("subscriptions")

    op.drop_index("ix_endpoints_owner_created_at_desc", table_name="endpoints")
    op.drop_index("ix_endpoints_created_at", table_name="endpoints")
    op.drop_index("ix_endpoints_owner_id", table_name="endpoints")
    op.drop_table("endpoints")

    op.drop_index("ix_sources_owner_created_at_desc", table_name="sources")
    op.drop_index("ix_sources_created_at", table_name="sources")
    op.drop_index("ix_sources_owner_id", table_name="sources")
    op.drop_table("sources")

    op.drop_index("ix_api_keys_owner_created_at_desc", table_name="api_keys")
    op.drop_index("ix_api_keys_created_at", table_name="api_keys")
    op.drop_index("ix_api_keys_owner_id", table_name="api_keys")
    op.drop_index("ix_api_keys_key_prefix", table_name="api_keys")
    op.drop_table("api_keys")

    op.drop_index("ix_users_created_at", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

