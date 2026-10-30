"""Safe diagnostics without a live database or provider exception output."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.exc import OperationalError


path = Path(__file__).resolve().parents[1] / "deploy" / "database_preflight.py"
spec = importlib.util.spec_from_file_location("database_preflight", path)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


class PreflightTests(unittest.TestCase):
    def test_driver_codes_are_explained_without_exception_secrets(self):
        for code, expected in ((1044, "permission"), (1045, "Authentication"),
                               (1049, "Unknown database"), (2003, "connection failed"),
                               (2005, "hostname"), (2026, "TLS"), (9999, "driver failure")):
            with self.subTest(code=code):
                error = OperationalError("secret SQL", {"password": "secret"}, Exception(code, "secret"))
                result = preflight.failure_reason(error)
                self.assertIn(expected, result)
                self.assertNotIn("secret", result)

    def run_preflight(self, error=None):
        config = ModuleType("app.core.config")
        config.DATABASE_URL = "mysql+pymysql://private-user:private-password@emailsender-mysql:3306/mail?token=private-token"
        engine = MagicMock()
        if error:
            engine.connect.side_effect = error
        output = io.StringIO()
        with patch.dict(sys.modules, {"app.core.config": config}), \
                patch.object(preflight, "create_engine", return_value=engine), \
                patch.object(preflight.time, "sleep"), contextlib.redirect_stdout(output):
            if error:
                with self.assertRaises(SystemExit) as caught:
                    preflight.main()
                output.write(str(caught.exception))
                self.assertEqual(engine.connect.call_count, 3)
            else:
                preflight.main()
        engine.dispose.assert_called_once()
        result = output.getvalue()
        for secret in ("private-user", "private-password", "private-token"):
            self.assertNotIn(secret, result)
        return result

    def test_failed_connection_reports_target_and_safe_reason(self):
        result = self.run_preflight(Exception(1045, "private-password"))
        self.assertIn("emailsender-mysql", result)
        self.assertIn("3306", result)
        self.assertIn("Authentication denied", result)
        self.assertIn("no application services were stopped", result)

    def test_success_reports_connectivity(self):
        self.assertIn("connectivity verified", self.run_preflight())

    def test_unknown_exception_does_not_leak_message(self):
        self.assertNotIn("private-password", preflight.failure_reason(ValueError("private-password")))
