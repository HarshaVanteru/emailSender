import unittest
import test_mailbox_reader as fixtures


class CanonicalApiTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.MailboxReaderTests.setUpClass.__func__)
    setUp = fixtures.MailboxReaderTests.setUp
    tearDown = fixtures.MailboxReaderTests.tearDown

    def test_account_routes_share_cache_and_reject_foreign_ownership(self):
        for account in (self.account, self.foreign):
            expected = 200 if account.id == self.account.id else 404
            for route in ('emails', 'threads', 'categories/primary', 'ai/important', 'ai/actions'):
                response = self.client.get(f'/api/v1/accounts/{account.id}/{route}')
                self.assertEqual(response.status_code, expected, (route, response.text))
        page = self.client.get(f'/api/v1/accounts/{self.account.id}/emails?limit=2').json()
        self.assertEqual(len(page['items']), 2)
        self.assertTrue(page['has_more_local'])
        self.assertEqual(page['next_cursor'], page['next_page_token'])
        self.assertEqual(page['historical_sync'], {'status': 'idle', 'session_id': None})
