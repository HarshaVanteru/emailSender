"""Store contextual AI suggestions separately from Gmail message cache."""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"


def upgrade():
    op.create_table(
        "ai_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("thread_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer()),
        sa.Column("operation", sa.String(24), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.ForeignKeyConstraint(["user_id", "account_id"], ["connected_accounts.user_id", "connected_accounts.id"],
                                name="fk_ai_suggestions_owner_account"),
        sa.ForeignKeyConstraint(["account_id", "thread_id"], ["email_threads.account_id", "email_threads.id"],
                                name="fk_ai_suggestions_account_thread", ondelete="CASCADE"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_bin",
    )
    op.create_index("ix_ai_suggestions_owner_thread_date", "ai_suggestions",
                    ["user_id", "account_id", "thread_id", "created_at"])


def downgrade():
    op.drop_index("ix_ai_suggestions_owner_thread_date", table_name="ai_suggestions")
    op.drop_table("ai_suggestions")
