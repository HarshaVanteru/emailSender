"""Separate application sessions and login identities from connected mailboxes."""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"


def upgrade():
    op.add_column("connected_accounts", sa.Column("google_sub", sa.String(255)))
    op.create_index("ix_connected_accounts_google_sub", "connected_accounts", ["google_sub"], unique=True)
    op.create_table("user_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime()))
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_table("login_identities",
        sa.Column("google_sub", sa.String(255), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False))
    op.create_index("ix_login_identities_user_id", "login_identities", ["user_id"])
    with op.batch_alter_table("oauth_attempts") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer()))
        batch.add_column(sa.Column("session_id", sa.String(64)))
        batch.add_column(sa.Column("account_id", sa.Integer()))
        batch.create_foreign_key("fk_oauth_attempt_owner", "users", ["user_id"], ["id"])
        batch.create_foreign_key("fk_oauth_attempt_account", "connected_accounts", ["account_id"], ["id"])


def downgrade():
    with op.batch_alter_table("oauth_attempts") as batch:
        batch.drop_constraint("fk_oauth_attempt_account", type_="foreignkey")
        batch.drop_constraint("fk_oauth_attempt_owner", type_="foreignkey")
        for field in ("account_id", "session_id", "user_id"):
            batch.drop_column(field)
    op.drop_table("login_identities")
    op.drop_table("user_sessions")
    op.drop_index("ix_connected_accounts_google_sub", table_name="connected_accounts")
    op.drop_column("connected_accounts", "google_sub")
