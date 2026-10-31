"""Identity separation uses real state, credentials, ownership and session logic."""
from datetime import timedelta
from unittest.mock import patch
import unittest

from fastapi import HTTPException

import test_connection_security as fixtures
from app.core.security import create_access_token, create_session, get_current_user
from app.core.time import utcnow
from app.features.google_login import accounts, oauth_state
from app.features.google_login.models import UserSession


credentials = fixtures.credentials


class MultiAccountTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.ConnectionSecurityTests.setUpClass.__func__)
    setUp = fixtures.ConnectionSecurityTests.setUp
    tearDown = fixtures.ConnectionSecurityTests.tearDown

    def test_two_oauth_callbacks_keep_application_identity_and_revoked_session_never_exchanges_code(self):
        from app.features.google_login.routes import gmail_service
        from app.features.google_login.models import ConnectedAccount
        from app.features.google_login.user import User
        from unittest.mock import MagicMock
        from urllib.parse import parse_qs, urlsplit
        flow = MagicMock()
        flow.authorization_url.return_value = ('https://accounts.google.com/test', 'unused')
        for email, subject in [('first@example.com', 'first-sub'), ('second@example.com', 'second-sub')]:
            with patch.object(gmail_service, 'create_google_flow', return_value=flow):
                response = self.client.post('/api/v1/accounts/google/connect')
                self.assertEqual(response.status_code, 200)
                state = flow.authorization_url.call_args.kwargs['state']
                with patch.object(gmail_service, 'exchange_google_code', return_value=credentials()), \
                     patch('app.features.google_login.routes.requests.get') as info:
                    info.return_value.json.return_value = {'email': email, 'sub': subject, 'email_verified': True}
                    callback = self.client.get('/api/v1/auth/google/callback', params={'state': state, 'code': 'test-code'}, follow_redirects=False)
            self.assertEqual(callback.status_code, 307)
            self.assertIn('token', parse_qs(urlsplit(callback.headers['location']).fragment))
        self.assertEqual(self.db.query(User).count(), 2)  # Only the original owner and other fixture user.
        self.assertEqual(self.db.query(ConnectedAccount).filter_by(user_id=self.user.id).count(), 2)
        session = create_session(self.db, self.user)
        state, browser, _ = oauth_state.create_attempt(self.db, user_id=self.user.id, session_id=session.id)
        session.revoked_at = utcnow(); self.db.commit()
        self.client.cookies.set(oauth_state.cookie_name(state), browser, path='/api')
        with patch.object(gmail_service, 'exchange_google_code') as exchange:
            response = self.client.get('/api/v1/auth/google/callback', params={'state': state, 'code': 'test-code'})
            self.assertEqual(response.status_code, 401)
            exchange.assert_not_called()
    def test_two_mailboxes_and_subject_ownership(self):
        for email, subject in (("first@example.com", "sub-first"), ("second@example.com", "sub-second")):
            account = accounts.save_connection(self.db, self.user, credentials(), email=email, google_sub=subject)
            self.assertEqual(account.user_id, self.user.id)
        response = self.client.get('/api/v1/accounts')
        self.assertEqual(len(response.json()), 2)
        self.assertNotIn('refresh-secret', response.text)
        self.assertNotIn('encrypted_credentials', response.text)
        with self.assertRaises(HTTPException):
            accounts.save_connection(self.db, self.other, credentials(), email="first@example.com", google_sub="sub-first")
        self.assertEqual(self.user.email, 'owner@example.com')
        self.assertTrue(self.client.get('/api/v1/gmail/profile').json()['is_connected'])

    def test_reconnect_cannot_replace_mailbox(self):
        first = accounts.save_connection(self.db, self.user, credentials(), email="first@example.com", google_sub="sub-first")
        with self.assertRaises(HTTPException):
            accounts.save_connection(self.db, self.user, credentials(), email="second@example.com", google_sub="sub-second", account_id=first.id)

    def test_connection_attempt_binds_owner_and_revocable_session(self):
        session = create_session(self.db, self.user)
        state, browser, _ = oauth_state.create_attempt(self.db, user_id=self.user.id, session_id=session.id)
        attempt = oauth_state.consume_attempt(self.db, state, browser)
        self.assertEqual((attempt.user_id, attempt.session_id), (self.user.id, session.id))
        token = create_access_token({'sub': self.user.email, 'sid': session.id})
        self.assertEqual(get_current_user(token, self.db).id, self.user.id)
        session.revoked_at = utcnow()
        self.db.commit()
        with self.assertRaises(HTTPException):
            get_current_user(token, self.db)
