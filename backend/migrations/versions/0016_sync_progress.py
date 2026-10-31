"""Persist committed sync progress and watch-renewal errors."""
from alembic import op
import sqlalchemy as sa

revision = '0016'
down_revision = '0015'


def upgrade():
    for column in ('messages_seen', 'messages_inserted', 'messages_updated'):
        op.add_column('sync_jobs', sa.Column(column, sa.Integer(), nullable=False, server_default='0'))
    op.add_column('connected_accounts', sa.Column('watch_last_error_code', sa.String(128)))


def downgrade():
    op.drop_column('connected_accounts', 'watch_last_error_code')
    for column in ('messages_updated', 'messages_inserted', 'messages_seen'):
        op.drop_column('sync_jobs', column)
