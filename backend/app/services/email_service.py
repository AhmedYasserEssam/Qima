from __future__ import annotations

import logging
import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage
from urllib.parse import quote_plus

from app.core.config import get_settings


class EmailService(ABC):
    @abstractmethod
    def send_verification_email(self, *, to_email: str, token: str) -> None:
        """Send a verification email containing a one-time token."""


class SmtpEmailService(EmailService):
    def send_verification_email(self, *, to_email: str, token: str) -> None:
        settings = get_settings()
        if not settings.smtp_host:
            raise RuntimeError("SMTP_HOST must be configured for SMTP email provider")

        verify_url = (
            f"{settings.email_verify_base_url}"
            f"?email={quote_plus(to_email)}&token={quote_plus(token)}"
        )

        message = EmailMessage()
        message["Subject"] = "Verify your Qima email"
        message["From"] = settings.email_from
        message["To"] = to_email
        message.set_content(
            "\n".join(
                [
                    "Welcome to Qima.",
                    "",
                    "Please verify your email address using the link below:",
                    verify_url,
                    "",
                    "If you did not request this, you can ignore this email.",
                ]
            )
        )

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_username and settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)


class ConsoleEmailService(EmailService):
    """Development fallback. Never use in production."""

    def send_verification_email(self, *, to_email: str, token: str) -> None:
        logging.warning(
            "DEV_EMAIL verification token generated for %s token=%s",
            to_email,
            token,
        )


def get_email_service() -> EmailService:
    settings = get_settings()
    if settings.email_provider == "smtp":
        if settings.app_env.lower() == "production":
            return SmtpEmailService()
        if settings.smtp_host:
            return SmtpEmailService()
        return ConsoleEmailService()
    raise RuntimeError(f"Unsupported email provider: {settings.email_provider}")
