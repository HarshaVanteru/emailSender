"""Move existing ciphertext without decrypting or discarding provider grants."""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"


def upgrade():
    op.create_table("oauth_credentials",
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("connected_accounts.id"), primary_key=True),
        sa.Column("encrypted_payload", sa.Text()),
        sa.Column("encryption_key_version", sa.String(50), nullable=False))
    op.execute(sa.text("INSERT INTO oauth_credentials (account_id, encrypted_payload, encryption_key_version) SELECT id, encrypted_credentials, 'v1' FROM connected_accounts WHERE encrypted_credentials IS NOT NULL"))
    op.execute(sa.text("UPDATE connected_accounts SET encrypted_credentials=NULL"))


def downgrade():
    accounts = sa.table("connected_accounts", sa.column("id"), sa.column("encrypted_credentials"))
    credentials = sa.table("oauth_credentials", sa.column("account_id"), sa.column("encrypted_payload"))
    op.get_bind().execute(accounts.update().values(encrypted_credentials=sa.select(credentials.c.encrypted_payload).where(
        credentials.c.account_id == accounts.c.id).scalar_subquery()))
    op.drop_table("oauth_credentials")
