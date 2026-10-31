"""Opt-in migrations against an explicitly named disposable MySQL database."""
import os
import unittest
from pathlib import Path
from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from app.core.database import Base
import app.features.google_login.models
import app.features.mailbox.models


@unittest.skipUnless(os.getenv('EMAIL_SENDER_TEST_MYSQL_URL'), 'Disposable MySQL URL not supplied')
class MySQLContractTests(unittest.TestCase):
    def test_clean_upgrade_existing_data_transition_and_downgrade(self):
        url = make_url(os.environ['EMAIL_SENDER_TEST_MYSQL_URL'])
        self.assertTrue((url.database or '').startswith('email_sender_test'), 'Refusing a non-test database')
        engine = create_engine(url)
        try:
            with engine.connect() as connection:
                tables = inspect(connection).get_table_names()
                if tables == ['alembic_version']:
                    self.assertEqual(connection.execute(text('SELECT COUNT(*) FROM alembic_version')).scalar(), 0)
                    connection.execute(text('DROP TABLE alembic_version'))
                    tables = []
                self.assertEqual(tables, [], 'Test database must start empty')
                connection.commit()
                config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
                config.attributes['connection'] = connection
                command.upgrade(config, '0009')
                connection.execute(text("INSERT INTO users (email) VALUES ('fixture@example.com')"))
                connection.execute(text("INSERT INTO connected_accounts (user_id,gmail_email,encrypted_credentials,scopes,requires_reauth) VALUES (1,'fixture@example.com','test-ciphertext','[]',0)"))
                connection.commit()
                command.upgrade(config, 'head')
                self.assertEqual(connection.execute(text('SELECT encrypted_payload FROM oauth_credentials')).scalar(), 'test-ciphertext')
                self.assertIsNone(connection.execute(text('SELECT encrypted_credentials FROM connected_accounts')).scalar())
                self.assertEqual(compare_metadata(MigrationContext.configure(connection), Base.metadata), [])
                connection.commit()
                self.assertTrue(inspect(connection).get_columns('users')[0]['type'].unsigned)
                connection.execute(text("INSERT INTO users (id,email) VALUES (2147483648,'wide-id@example.com')"))
                connection.commit()
                with self.assertRaisesRegex(RuntimeError, 'target type'):
                    command.downgrade(config, '0014')
                connection.rollback()
                self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM users WHERE id=2147483648")).scalar(), 1)
                connection.execute(text('DELETE FROM users WHERE id=2147483648'))
                connection.commit()
                command.downgrade(config, '0009')
                self.assertEqual(connection.execute(text('SELECT encrypted_credentials FROM connected_accounts')).scalar(), 'test-ciphertext')
                connection.commit()
                command.upgrade(config, 'head')
                command.downgrade(config, '0002')
                # Revision 0002's intentional plaintext downgrade requires an
                # actual encryption key; no real credentials are used here.
                connection.execute(text('DELETE FROM connected_accounts'))
                connection.commit()
                command.downgrade(config, 'base')
                connection.execute(text('DROP TABLE alembic_version'))
                connection.commit()
        finally:
            engine.dispose()
