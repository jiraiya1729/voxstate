from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_agent_routing"
down_revision: str | None = "0002_call_failure"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("language", sa.String(32), nullable=False),
        sa.Column("bedrock_model_id", sa.String(255), nullable=False),
        sa.Column("bedrock_timeout_seconds", sa.Float(), nullable=False),
        sa.Column("cartesia_voice_id", sa.String(255), nullable=False),
        sa.Column("cartesia_tts_model_id", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
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
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "phone_number_routes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("phone_number", sa.String(32)),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
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
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phone_number"),
    )
    op.create_index(
        "uq_phone_number_routes_fallback",
        "phone_number_routes",
        [sa.text("(1)")],
        unique=True,
        postgresql_where=sa.text("phone_number IS NULL"),
    )
    op.create_table(
        "routing_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("called_number", sa.String(32)),
        sa.Column("language", sa.String(32)),
        sa.Column("category", sa.String(64)),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
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
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "called_number IS NOT NULL OR language IS NOT NULL OR category IS NOT NULL",
            name="ck_routing_rule_has_signal",
        ),
    )
    op.add_column(
        "calls",
        sa.Column(
            "direction", sa.String(16), server_default="outbound", nullable=False
        ),
    )
    op.add_column("calls", sa.Column("from_phone_number", sa.String(32)))
    op.add_column("calls", sa.Column("initial_agent_id", sa.Uuid()))
    op.add_column("calls", sa.Column("active_agent_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_calls_initial_agent", "calls", "agents", ["initial_agent_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_calls_active_agent", "calls", "agents", ["active_agent_id"], ["id"]
    )
    op.create_table(
        "call_transfers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("source_agent_id", sa.Uuid()),
        sa.Column("target_agent_id", sa.Uuid()),
        sa.Column("target_phone_number", sa.String(32)),
        sa.Column("status", sa.String(24), nullable=False),
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
        sa.ForeignKeyConstraint(["source_agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["target_agent_id"], ["agents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "call_id", "idempotency_key", name="uq_call_transfer_idempotency"
        ),
    )


def downgrade() -> None:
    op.drop_table("call_transfers")
    op.drop_constraint("fk_calls_active_agent", "calls", type_="foreignkey")
    op.drop_constraint("fk_calls_initial_agent", "calls", type_="foreignkey")
    op.drop_column("calls", "active_agent_id")
    op.drop_column("calls", "initial_agent_id")
    op.drop_column("calls", "from_phone_number")
    op.drop_column("calls", "direction")
    op.drop_table("routing_rules")
    op.drop_index("uq_phone_number_routes_fallback", table_name="phone_number_routes")
    op.drop_table("phone_number_routes")
    op.drop_table("agents")
