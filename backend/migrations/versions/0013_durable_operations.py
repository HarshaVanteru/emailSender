"""Independent durable AI and sending work, including ambiguous send outcomes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import LONGTEXT

revision = "0013"
down_revision = "0012"


def upgrade():
    for table, suffix in (("email_send_jobs", "send"), ("ai_processing_jobs", "ai")):
        fields = [
            sa.Column("internal_id", sa.Integer(), primary_key=True),
            sa.Column("id", sa.String(64), nullable=False, unique=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("account_id", sa.Integer(), sa.ForeignKey("connected_accounts.id"), nullable=suffix == "ai"),
            sa.Column("idempotency_key", sa.String(150), nullable=False),
            sa.Column("input_hash", sa.String(64), nullable=False),
            sa.Column("operation", sa.String(32), nullable=False),
            sa.Column("status", sa.String(24), nullable=False),
            sa.Column("payload_ciphertext", sa.Text().with_variant(LONGTEXT(), "mysql")),
            sa.Column("result", sa.JSON()),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("available_at", sa.DateTime(), nullable=False),
            sa.Column("lease_expires_at", sa.DateTime()),
            sa.Column("lease_token", sa.String(64)),
            sa.Column("error_code", sa.String(128)),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime()),
            sa.UniqueConstraint("account_id" if suffix == "send" else "user_id", "idempotency_key", name=f"uq_{suffix}_idempotency"),
        ]
        fields += ([sa.Column("rfc_message_id", sa.String(255))] if suffix == "send" else
                   [sa.Column("thread_id", sa.Integer(), nullable=False)])
        op.create_table(table, *fields)
        op.create_index(f"ix_{table}_status", table, ["status"])


def downgrade():
    op.drop_table("ai_processing_jobs")
    op.drop_table("email_send_jobs")
