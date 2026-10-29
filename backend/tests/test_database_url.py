import unittest
from sqlalchemy.engine import make_url
from app.core.database_url import resolve_database_url


class DatabaseUrlTests(unittest.TestCase):
    def test_local_mysql_routes_directly_without_changing_encoded_credentials(self):
        original = 'mysql+pymysql://app:p%40ss%3Aword%2Fvalue@host.docker.internal:3306/mail?charset=utf8mb4'
        before = make_url(original)
        after = make_url(resolve_database_url(original, 'emailsender-mysql'))
        self.assertEqual(after.host, 'emailsender-mysql')
        for field in ('drivername', 'username', 'password', 'port', 'database', 'query'):
            self.assertEqual(getattr(before, field), getattr(after, field))

    def test_explicit_external_database_and_sqlite_are_unchanged(self):
        for value in ('mysql+pymysql://app:secret@db.example.com:3306/mail', 'sqlite://'):
            self.assertEqual(resolve_database_url(value, 'emailsender-mysql'), value)

    def test_without_override_original_url_is_unchanged(self):
        original = 'mysql+pymysql://app:secret@host.docker.internal:3306/mail'
        self.assertEqual(resolve_database_url(original), original)
