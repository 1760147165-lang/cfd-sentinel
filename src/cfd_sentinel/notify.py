"""Email notifications without storing credentials in project files."""

from __future__ import annotations

import os
import smtplib
import ssl
import sys
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Mapping, Optional


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class EmailSettings:
    recipient: str
    host: str
    port: int
    sender: str
    username: str
    password: str
    use_ssl: bool
    use_starttls: bool

    @classmethod
    def from_environment(
        cls,
        recipient: str,
        environment: Optional[Mapping[str, str]] = None,
    ) -> "EmailSettings":
        values = environment or os.environ
        host = values.get("CFD_SENTINEL_SMTP_HOST", "").strip()
        sender = values.get("CFD_SENTINEL_SMTP_FROM", "").strip()
        username = values.get("CFD_SENTINEL_SMTP_USERNAME", "").strip()
        password = values.get("CFD_SENTINEL_SMTP_PASSWORD", "")
        use_ssl = _truthy(values.get("CFD_SENTINEL_SMTP_SSL", "false"))
        use_starttls = _truthy(values.get("CFD_SENTINEL_SMTP_STARTTLS", "true"))
        default_port = 465 if use_ssl else 587
        port = int(values.get("CFD_SENTINEL_SMTP_PORT", str(default_port)))
        missing = [
            name
            for name, value in (
                ("CFD_SENTINEL_SMTP_HOST", host),
                ("CFD_SENTINEL_SMTP_FROM", sender),
                ("CFD_SENTINEL_SMTP_PASSWORD", password),
            )
            if not value
        ]
        if missing:
            raise ValueError("missing email environment variables: {}".format(", ".join(missing)))
        return cls(
            recipient=recipient,
            host=host,
            port=port,
            sender=sender,
            username=username,
            password=password,
            use_ssl=use_ssl,
            use_starttls=use_starttls,
        )


class Notifier:
    def __init__(
        self,
        recipient: Optional[str],
        dry_run: bool = False,
        settings: Optional[EmailSettings] = None,
    ) -> None:
        self.recipient = recipient
        self.dry_run = dry_run
        self.settings = settings

    def send(self, subject: str, body: str) -> bool:
        if not self.recipient:
            return True
        if self.dry_run:
            print("\n--- CFD Sentinel email preview ---")
            print("To: {}".format(self.recipient))
            print("Subject: {}".format(subject))
            print(body)
            print("--- end preview ---\n")
            return True
        try:
            settings = self.settings or EmailSettings.from_environment(self.recipient)
            message = EmailMessage()
            message["From"] = settings.sender
            message["To"] = settings.recipient
            message["Subject"] = subject
            message.set_content(body)
            context = ssl.create_default_context()
            if settings.use_ssl:
                with smtplib.SMTP_SSL(
                    settings.host, settings.port, timeout=30, context=context
                ) as client:
                    if settings.username:
                        client.login(settings.username, settings.password)
                    client.send_message(message)
                return True
            with smtplib.SMTP(settings.host, settings.port, timeout=30) as client:
                client.ehlo()
                if settings.use_starttls:
                    client.starttls(context=context)
                    client.ehlo()
                if settings.username:
                    client.login(settings.username, settings.password)
                client.send_message(message)
            return True
        except Exception as exc:
            print(
                "CFD Sentinel warning: email delivery failed: {}".format(exc),
                file=sys.stderr,
            )
            return False
