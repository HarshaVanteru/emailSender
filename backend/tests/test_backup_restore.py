"""Real dump/restore drill, opt-in and confined to a labeled disposable container."""
import os
import subprocess
import unittest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


@unittest.skipUnless(os.getenv('EMAIL_SENDER_TEST_MYSQL_CONTAINER'), 'Disposable Docker MySQL not supplied')
class BackupRestoreTests(unittest.TestCase):
    def test_backup_restores_fixture_into_separate_database(self):
        container = os.environ['EMAIL_SENDER_TEST_MYSQL_CONTAINER']
        url = make_url(os.environ['EMAIL_SENDER_TEST_MYSQL_URL'])
        self.assertTrue((url.database or '').startswith('email_sender_test'))
        labels = subprocess.check_output(['docker', 'inspect', '--format', '{{index .Config.Labels "emailsender.task"}}', container], text=True).strip()
        self.assertEqual(labels, 'architecture-review', 'Only the disposable test container is allowed')
        target = 'email_sender_test_restored'
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE restore_drill (id INTEGER PRIMARY KEY, value VARCHAR(50) NOT NULL)'))
            connection.execute(text("INSERT INTO restore_drill VALUES (1,'fixture-only')"))
        command = ['docker', 'exec', '-e', 'MYSQL_PWD=' + (url.password or ''), container]
        try:
            dump = subprocess.check_output([*command, 'mysqldump', '-uroot', '--single-transaction', '--no-tablespaces', '--set-gtid-purged=OFF', url.database])
            subprocess.run([*command, 'mysql', '-uroot', '-e', 'CREATE DATABASE ' + target], check=True)
            subprocess.run(['docker', 'exec', '-i', '-e', 'MYSQL_PWD=' + (url.password or ''), container,
                            'mysql', '-uroot', target], input=dump, check=True)
            restored = create_engine(url.set(database=target))
            try:
                with restored.connect() as connection:
                    self.assertEqual(connection.execute(text('SELECT value FROM restore_drill WHERE id=1')).scalar(), 'fixture-only')
            finally:
                restored.dispose()
        finally:
            with engine.begin() as connection:
                connection.execute(text('DROP TABLE restore_drill'))
            engine.dispose()
            subprocess.run([*command, 'mysql', '-uroot', '-e', 'DROP DATABASE IF EXISTS ' + target], check=True)
