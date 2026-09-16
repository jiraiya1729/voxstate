from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_event_ledger"
down_revision: str | None = "0003_agent_routing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("call_id", sa.Uuid()),
        sa.Column("sequence", sa.Integer()),
        sa.Column("correlation_id", sa.String(128)),
        sa.Column("idempotency_key", sa.String(255)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("call_id", "sequence", name="uq_events_call_sequence"),
        sa.UniqueConstraint("idempotency_key", name="uq_events_idempotency_key"),
    )
    op.create_index("ix_events_call_id_sequence", "events", ["call_id", "sequence"])
    op.create_index("ix_events_event_type", "events", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_events_event_type", table_name="events")
    op.drop_index("ix_events_call_id_sequence", table_name="events")
    op.drop_table("events")
