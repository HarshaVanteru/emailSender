import unittest
from unittest.mock import MagicMock
from sqlalchemy.orm import sessionmaker
import test_context_ai as fixtures
from app.features.ai_assistant import jobs
from app.features.ai_assistant.context_schemas import ContextAiRequest
from app.features.mailbox.models import AiSuggestion
from app.workers.operation_models import AiJob
from app.workers import operations


class AiJobTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.ContextAiTests.setUpClass.__func__)
    setUp = fixtures.ContextAiTests.setUp
    tearDown = fixtures.ContextAiTests.tearDown

    def test_submission_is_idempotent_and_does_not_invoke_model(self):
        from unittest.mock import patch
        from cryptography.fernet import Fernet
        with patch('app.core.config.TOKEN_ENCRYPTION_KEY', Fernet.generate_key().decode()):
            first = jobs.enqueue(self.db, self.owner.id, self.account.id, self.thread.id, 'summarize', ContextAiRequest())
            again = jobs.enqueue(self.db, self.owner.id, self.account.id, self.thread.id, 'summarize', ContextAiRequest())
            self.assertEqual(first.id, again.id)
            self.assertEqual(self.db.query(AiJob).count(), 1)
            self.model.invoke.assert_not_called()
            self.model.invoke.return_value = {'summary': 'A concise summary'}
            factory = sessionmaker(self.engine)
            executor = lambda db, row, data: jobs.execute_job(db, row, data, self.model)
            operations.process('ai', first.id, factory, executor)
            operations.process('ai', first.id, factory, executor)
            self.db.expire_all()
            self.assertEqual(self.db.query(AiJob).filter_by(id=first.id).first().status, 'completed')
            self.assertEqual(self.db.query(AiSuggestion).count(), 1)
            self.model.invoke.assert_called_once()
