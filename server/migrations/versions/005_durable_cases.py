from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_durable_cases"
down_revision: str | None = "0004_event_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer_reference_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), server_default="open", nullable=False),
        sa.Column(
            "business_state", sa.String(64), server_default="new", nullable=False
        ),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_outcome", sa.JSON()),
        sa.Column("callback_at", sa.DateTime(timezone=True)),
        sa.Column("customer_state", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
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
    op.add_column("calls", sa.Column("case_id", sa.Uuid()))
    op.create_foreign_key("fk_calls_case", "calls", "cases", ["case_id"], ["id"])
    op.create_index("ix_calls_case_id", "calls", ["case_id"])


def downgrade() -> None:
    op.drop_index("ix_calls_case_id", table_name="calls")
    op.drop_constraint("fk_calls_case", "calls", type_="foreignkey")
    op.drop_column("calls", "case_id")
    op.drop_table("cases")
