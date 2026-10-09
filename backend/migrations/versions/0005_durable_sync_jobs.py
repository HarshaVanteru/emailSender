"""Durable outbox, single active account job, worker leases, and sync schedules."""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"


def upgrade():
    # Stop the old API before migration. Its synchronous running records have no
    # recoverable lease; retain them as explicit failures rather than invent one.
    op.execute(sa.text("UPDATE sync_jobs SET status='failed', error_code='migration_interrupted', "
                       "finished_at=CURRENT_TIMESTAMP WHERE status IN ('queued','running')"))
    with op.batch_alter_table("sync_jobs") as batch:
        batch.add_column(sa.Column("active_account_id", sa.Integer()))
        batch.add_column(sa.Column("available_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()))
        batch.add_column(sa.Column("dispatch_after", sa.DateTime()))
        batch.add_column(sa.Column("lease_token", sa.String(64)))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime()))
        batch.create_unique_constraint("uq_sync_jobs_active_account", ["active_account_id"])
        batch.create_check_constraint("ck_sync_jobs_active_account", "active_account_id IS NULL OR (active_account_id = account_id AND status IN ('queued', 'running'))")
        batch.create_index("ix_sync_jobs_dispatch", ["status", "available_at", "dispatch_after"])
        batch.create_index("ix_sync_jobs_lease", ["status", "lease_expires_at"])
    op.add_column("connected_accounts", sa.Column("next_sync_at", sa.DateTime()))
    op.add_column("connected_accounts", sa.Column("next_reconcile_at", sa.DateTime()))
    op.add_column("connected_accounts", sa.Column("sync_paused", sa.Boolean(), nullable=False, server_default="0"))
    op.create_index("ix_connected_accounts_next_sync_at", "connected_accounts", ["next_sync_at"])


def downgrade():
    # Callers must stop workers/scheduler first; queued work cannot run on 0004.
    op.execute(sa.text("UPDATE sync_jobs SET status='failed', active_account_id=NULL, "
                       "error_code='migration_interrupted', finished_at=CURRENT_TIMESTAMP "
                       "WHERE status IN ('queued','running')"))
    with op.batch_alter_table("sync_jobs") as batch:
        batch.drop_index("ix_sync_jobs_lease")
        batch.drop_index("ix_sync_jobs_dispatch")
        batch.drop_constraint("ck_sync_jobs_active_account", type_="check")
        batch.drop_constraint("uq_sync_jobs_active_account", type_="unique")
        for column in ("lease_expires_at", "lease_token", "dispatch_after", "available_at", "active_account_id"):
            batch.drop_column(column)
    # Native column drops avoid rebuilding a parent table with live mailbox FKs
    # on SQLite 3.35+, while also compiling directly for MySQL 8.
    op.drop_index("ix_connected_accounts_next_sync_at", table_name="connected_accounts")
    op.drop_column("connected_accounts", "next_reconcile_at")
    op.drop_column("connected_accounts", "next_sync_at")
    op.drop_column("connected_accounts", "sync_paused")
