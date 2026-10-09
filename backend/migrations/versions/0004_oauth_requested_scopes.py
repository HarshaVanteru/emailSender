"""Persist the exact opt-in mailbox OAuth scopes across redirect/workers."""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"


def upgrade():
    # NULL preserves compatibility with pre-upgrade pending send-only attempts.
    op.add_column("oauth_attempts", sa.Column("requested_scopes", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("oauth_attempts") as batch:
        batch.drop_column("requested_scopes")
