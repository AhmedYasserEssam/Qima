from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="development", alias="APP_ENV")

    jwt_secret: str = Field(default="dev_jwt_secret_change_me", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_access_token_exp_minutes: int = Field(
        default=60,
        alias="JWT_ACCESS_TOKEN_EXP_MINUTES",
    )

    verification_secret: str = Field(
        default="dev_verification_secret_change_me",
        alias="VERIFICATION_SECRET",
    )
    verification_token_ttl_minutes: int = Field(
        default=30,
        alias="VERIFICATION_TOKEN_TTL_MINUTES",
    )
    verification_resend_cooldown_seconds: int = Field(
        default=60,
        alias="VERIFICATION_RESEND_COOLDOWN_SECONDS",
    )

    email_provider: str = Field(default="smtp", alias="EMAIL_PROVIDER")
    email_from: str = Field(default="no-reply@qima.local", alias="EMAIL_FROM")
    email_verify_base_url: str = Field(
        default="http://localhost:8000/verify-email",
        alias="EMAIL_VERIFY_BASE_URL",
    )
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: str = Field(default="", alias="SMTP_USERNAME")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_use_tls: bool = Field(default=True, alias="SMTP_USE_TLS")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
