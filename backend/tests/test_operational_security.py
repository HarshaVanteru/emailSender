import unittest
from unittest.mock import MagicMock, patch
from datetime import timedelta
import fakeredis
from cryptography.fernet import Fernet
from fastapi import HTTPException
from app.core import config
from app.core.observability import check_limit, rate_identity
from app.core.token_crypto import encrypt, decrypt
from app.workers.supervisor import commands
from app.features.mail_sync.jobs import retry_after_seconds
from test_gmail_sync import error


class OperationalSecurityTests(unittest.TestCase):
    def test_missing_model_configuration_cannot_break_application_startup(self):
        from app.features.ai_assistant.service import AiService
        with patch('app.features.ai_assistant.service.ChatGroq') as model:
            service = AiService()
            model.assert_not_called()
            self.assertNotIn('llm', service.__dict__)
    def test_rate_limit_is_shared_and_keys_contain_no_bearer(self):
        client = fakeredis.FakeRedis()
        with patch.object(config, 'API_REQUESTS_PER_MINUTE', 2):
            self.assertTrue(check_limit('Bearer private-token', client)[0])
            self.assertTrue(check_limit('Bearer private-token', client)[0])
            allowed, ttl = check_limit('Bearer private-token', client)
            self.assertFalse(allowed)
            self.assertGreater(ttl, 0)
        self.assertNotIn('private-token', str(client.keys()))

    def test_different_sessions_share_the_same_user_rate_budget(self):
        from app.core.security import create_access_token
        with patch.object(config, 'SECRET_KEY', 'test-key-at-least-32-characters-long'):
            first = create_access_token({'sub': 'owner@example.com', 'sid': 'first'})
            second = create_access_token({'sub': 'owner@example.com', 'sid': 'second'})
            self.assertEqual(rate_identity('Bearer ' + first, 'address-a'), rate_identity('Bearer ' + second, 'address-b'))

    def test_key_rotation_reads_old_ciphertext_and_writes_with_new_key(self):
        old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
        with patch.object(config, 'TOKEN_ENCRYPTION_KEY', old):
            original = encrypt('test-credential')
        with patch.object(config, 'TOKEN_ENCRYPTION_KEY', new), patch.object(config, 'TOKEN_ENCRYPTION_PREVIOUS_KEYS', old):
            self.assertEqual(decrypt(original), 'test-credential')
            rotated = encrypt('test-credential')
        self.assertEqual(Fernet(new.encode()).decrypt(rotated.encode()), b'test-credential')

    def test_queue_processes_reserve_capacity_and_retry_after_is_respected(self):
        specs = commands()
        self.assertEqual(len(specs), 3)
        self.assertIn('gmail-sync,gmail-maintenance', specs[0])
        self.assertIn('gmail-ai', specs[1])
        self.assertIn('gmail-send', specs[2])
        exc = error(429)
        exc.resp['retry-after'] = '120'
        self.assertEqual(retry_after_seconds(exc), 120)
