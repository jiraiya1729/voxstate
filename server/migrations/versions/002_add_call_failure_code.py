import sqlalchemy as sa
from alembic import op

revision: str = "0002_call_failure"
down_revision: str | None = "0001_create_calls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "calls",
        sa.Column("failure_code", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("calls", "failure_code")
