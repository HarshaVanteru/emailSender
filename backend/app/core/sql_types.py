from sqlalchemy import Integer
from sqlalchemy.dialects.mysql import BIGINT

# SQLite requires INTEGER for autoincrement primary keys in deterministic tests.
ID_TYPE = Integer().with_variant(BIGINT(unsigned=True), 'mysql')
