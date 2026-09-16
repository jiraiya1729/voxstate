from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_events_controls"
down_revision: str | None = "0007_timers_callbacks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_external_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("correlation_key", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("payload", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("status", sa.String(32), server_default="unmatched", nullable=False),
        sa.Column("subscription_id", sa.Uuid()),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_workflow_external_event_key"),
    )
    op.create_table(
        "workflow_event_subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.String(80), nullable=False),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("correlation_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("on_event_step_id", sa.String(80), nullable=False),
        sa.Column("on_timeout_step_id", sa.String(80)),
        sa.Column("matched_event_id", sa.Uuid()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id", "step_id", name="uq_workflow_event_subscription_step"
        ),
    )
    op.create_index(
        "ix_workflow_event_subscriptions_match",
        "workflow_event_subscriptions",
        ["event_type", "correlation_key", "status"],
    )
    op.create_index(
        "ix_workflow_external_events_match",
        "workflow_external_events",
        ["event_type", "correlation_key"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_external_events_match",
        table_name="workflow_external_events",
    )
    op.drop_index(
        "ix_workflow_event_subscriptions_match",
        table_name="workflow_event_subscriptions",
    )
    op.drop_table("workflow_event_subscriptions")
    op.drop_table("workflow_external_events")
