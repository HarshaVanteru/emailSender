"""Widen numeric identifiers together; run with application writers stopped."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT

revision = '0015'
down_revision = '0014'


def convert(widen):
    connection = op.get_bind()
    if connection.dialect.name != 'mysql':
        return
    inspector = sa.inspect(connection)
    tables = [table for table in inspector.get_table_names() if table != 'alembic_version']
    columns = {table: [column for column in inspector.get_columns(table)
        if isinstance(column['type'], sa.Integer) and (column['name'] == 'id' or column['name'].endswith('_id'))]
        for table in tables}
    quote = connection.dialect.identifier_preparer.quote
    # Validate every value before MySQL's implicitly committed DDL begins.
    for table, items in columns.items():
        for column in items:
            field = quote(column['name'])
            low, high = connection.execute(sa.text(f'SELECT MIN({field}), MAX({field}) FROM {quote(table)}')).one()
            if (low is not None and low < 0) or (not widen and high is not None and high > 2**31 - 1):
                raise RuntimeError('Identifier conversion requires values that fit the target type.')
    foreign_keys = {table: inspector.get_foreign_keys(table) for table in tables}
    for table, keys in foreign_keys.items():
        for key in keys:
            op.drop_constraint(key['name'], table, type_='foreignkey')
    for table, items in columns.items():
        for column in items:
            op.alter_column(table, column['name'], existing_type=column['type'],
                type_=BIGINT(unsigned=True) if widen else sa.Integer(),
                existing_nullable=column['nullable'], autoincrement=bool(column.get('autoincrement')))
    for table, keys in foreign_keys.items():
        for key in keys:
            op.create_foreign_key(key['name'], table, key['referred_table'], key['constrained_columns'],
                key['referred_columns'], **(key.get('options') or {}))


def upgrade():
    convert(True)


def downgrade():
    convert(False)
