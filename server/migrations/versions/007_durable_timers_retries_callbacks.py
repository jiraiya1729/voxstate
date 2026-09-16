from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_timers_callbacks"
down_revision: str | None = "0006_workflow_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_activity_attempts",
        sa.Column("attempt_number", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column("workflow_activity_attempts", sa.Column("outcome", sa.JSON()))
    op.create_table(
        "workflow_timers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("wake_step_id", sa.String(80), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("payload", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("fired_at", sa.DateTime(timezone=True)),
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
        sa.UniqueConstraint("idempotency_key", name="uq_workflow_timer_idempotency"),
    )
    op.create_index(
        "ix_workflow_timers_due",
        "workflow_timers",
        ["status", "due_at"],
    )
    op.create_index(
        "ix_workflow_timers_run_id",
        "workflow_timers",
        ["run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_timers_run_id", table_name="workflow_timers")
    op.drop_index("ix_workflow_timers_due", table_name="workflow_timers")
    op.drop_table("workflow_timers")
    op.drop_column("workflow_activity_attempts", "outcome")
    op.drop_column("workflow_activity_attempts", "attempt_number")
