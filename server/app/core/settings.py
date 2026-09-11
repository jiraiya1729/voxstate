import os
from enum import StrEnum
from functools import lru_cache
from typing import Self

from pydantic import (
    AnyHttpUrl,
    PostgresDsn,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.types import E164number


class RuntimeMode(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="VOXSTATE_",
        case_sensitive=False,
        extra="ignore",
    )

    runtime_mode: RuntimeMode = RuntimeMode.DEVELOPMENT
    public_base_url: AnyHttpUrl

    database_url: PostgresDsn
    supabase_url: AnyHttpUrl
    supabase_service_role_key: SecretStr

    twilio_account_sid: str
    twilio_auth_token: SecretStr
    twilio_phone_number: E164number

    cartesia_api_key: SecretStr
    cartesia_voice_id: str

    aws_region: str
    bedrock_model_id: str

    @field_validator(
        "twilio_account_sid",
        "twilio_phone_number",
        "aws_region",
        "bedrock_model_id",
        "cartesia_voice_id",
    )
    @classmethod
    def reject_empty_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator(
        "supabase_service_role_key",
        "twilio_auth_token",
        "cartesia_api_key",
    )
    @classmethod
    def reject_empty_secret(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def prevent_production_configuration_during_tests(self) -> Self:
        if self.runtime_mode is RuntimeMode.PRODUCTION and os.getenv(
            "PYTEST_CURRENT_TEST"
        ):
            raise ValueError(
                "Production configuration cannot be loaded while pytest is running"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
