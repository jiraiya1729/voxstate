from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_workflow_runtime"
down_revision: str | None = "0005_durable_cases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_definitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("definition_id", sa.Uuid(), nullable=False),
        sa.Column("definition_snapshot", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("current_step_id", sa.String(80), nullable=False),
        sa.Column("completed_step_ids", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("last_call_id", sa.Uuid()),
        sa.Column("failure_code", sa.String(64)),
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
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.ForeignKeyConstraint(["definition_id"], ["workflow_definitions.id"]),
        sa.ForeignKeyConstraint(["last_call_id"], ["calls.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "workflow_activity_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("call_id", sa.Uuid()),
        sa.Column("failure_code", sa.String(64)),
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
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "idempotency_key",
            name="uq_workflow_activity_attempt_effect",
        ),
    )
    op.create_index("ix_workflow_runs_case_id", "workflow_runs", ["case_id"])
    op.create_index(
        "ix_workflow_activity_attempts_run_id",
        "workflow_activity_attempts",
        ["run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_activity_attempts_run_id",
        table_name="workflow_activity_attempts",
    )
    op.drop_index("ix_workflow_runs_case_id", table_name="workflow_runs")
    op.drop_table("workflow_activity_attempts")
    op.drop_table("workflow_runs")
    op.drop_table("workflow_definitions")
