"""Durable OAuth attempts and encrypted Gmail connections; explicit legacy import."""
import json

from alembic import op
import sqlalchemy as sa

from app.core.token_crypto import cipher

revision = "0002"
down_revision = "0001"


def upgrade():
    connection = op.get_bind()
    users = sa.table("users", sa.column("id"), sa.column("email"), sa.column("google_token"))
    legacy = list(connection.execute(sa.select(users).where(users.c.google_token.is_not(None))).mappings())
    # Validate/encrypt every row BEFORE DDL (MySQL DDL commits implicitly).
    encrypted = []
    if legacy:
        key = cipher()
        for user in legacy:
            data = json.loads(user["google_token"])
            encrypted.append({"user_id": user["id"], "gmail_email": user["email"],
                              "encrypted_credentials": key.encrypt(user["google_token"].encode()).decode(),
                              "scopes": json.dumps(data.get("scopes", [])), "requires_reauth": False})
    accounts = op.create_table("connected_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("gmail_email", sa.String(255), nullable=False, unique=True),
        sa.Column("encrypted_credentials", sa.Text()),
        sa.Column("scopes", sa.Text(), nullable=False),
        sa.Column("profile_history_id", sa.String(255)),
        sa.Column("requires_reauth", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_connected_accounts_user_id", "connected_accounts", ["user_id"])
    op.create_table("oauth_attempts",
        sa.Column("state_hash", sa.String(64), primary_key=True),
        sa.Column("browser_hash", sa.String(64), nullable=False),
        sa.Column("encrypted_verifier", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_oauth_attempts_expires_at", "oauth_attempts", ["expires_at"])
    if encrypted:
        connection.execute(accounts.insert(), encrypted)
        connection.execute(users.update().where(users.c.google_token.is_not(None)).values(google_token=None))


def downgrade():
    connection = op.get_bind()
    accounts = sa.table("connected_accounts", sa.column("user_id"), sa.column("encrypted_credentials"))
    rows = list(connection.execute(sa.select(accounts).where(accounts.c.encrypted_credentials.is_not(None))).mappings())
    restored = []
    if rows:
        key = cipher()
        for row in rows:
            token = key.decrypt(row["encrypted_credentials"].encode()).decode()
            if len(token) > 2048:
                raise RuntimeError("Credentials exceed the legacy column size. Export securely before rollback.")
            restored.append((row["user_id"], token))
    # An explicit downgrade restores the original plaintext storage contract.
    users = sa.table("users", sa.column("id"), sa.column("google_token"))
    for user_id, token in restored:
        connection.execute(users.update().where(users.c.id == user_id).values(google_token=token))
    op.drop_table("oauth_attempts")
    op.drop_table("connected_accounts")
