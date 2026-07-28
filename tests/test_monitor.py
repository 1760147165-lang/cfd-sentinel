import time
import unittest
from unittest import mock

from cfd_sentinel.monitor import LogState
from cfd_sentinel.notify import EmailSettings, Notifier


class LogStateTests(unittest.TestCase):
    def test_fluent_residual_line_updates_iteration(self):
        state = LogState()
        previous = state.last_progress_time
        time.sleep(0.001)
        state.consume("  1000  1.2174e-02  1.0468e-05  1.7366e-05  0:00:00\n")
        self.assertEqual(state.last_iteration, 1000)
        self.assertGreater(state.last_progress_time, previous)

    def test_known_fatal_marker_is_collected_once(self):
        state = LogState()
        state.consume("Error: No journal response to dialog box\n")
        state.consume("Error: No journal response to dialog box\n")
        self.assertEqual(len(state.fatal_lines), 1)


class EmailSettingsTests(unittest.TestCase):
    def test_environment_settings_do_not_require_username(self):
        settings = EmailSettings.from_environment(
            "recipient@example.com",
            {
                "CFD_SENTINEL_SMTP_HOST": "smtp.example.com",
                "CFD_SENTINEL_SMTP_FROM": "sender@example.com",
                "CFD_SENTINEL_SMTP_PASSWORD": "secret",
            },
        )
        self.assertEqual(settings.port, 587)
        self.assertTrue(settings.use_starttls)

    def test_missing_password_is_rejected(self):
        with self.assertRaises(ValueError):
            EmailSettings.from_environment(
                "recipient@example.com",
                {
                    "CFD_SENTINEL_SMTP_HOST": "smtp.example.com",
                    "CFD_SENTINEL_SMTP_FROM": "sender@example.com",
                },
            )

    def test_delivery_failure_does_not_raise(self):
        settings = EmailSettings(
            recipient="recipient@example.com",
            host="smtp.example.com",
            port=587,
            sender="sender@example.com",
            username="sender@example.com",
            password="secret",
            use_ssl=False,
            use_starttls=True,
        )
        notifier = Notifier("recipient@example.com", settings=settings)
        with mock.patch("cfd_sentinel.notify.smtplib.SMTP", side_effect=OSError("offline")):
            self.assertFalse(notifier.send("subject", "body"))


if __name__ == "__main__":
    unittest.main()
