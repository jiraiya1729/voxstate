import pytest
from pydantic import ValidationError

from app.core.settings import RuntimeMode, Settings

VALID_ENVIRONMENT = {
    "VOXSTATE_RUNTIME_MODE": "test",
    "VOXSTATE_DATABASE_URL": (
        "postgresql://postgres:postgres@localhost:5432/voxstate_test"
    ),
    "VOXSTATE_SUPABASE_URL": "https://example.supabase.co",
    "VOXSTATE_SUPABASE_SERVICE_ROLE_KEY": "supabase-secret",
    "VOXSTATE_TWILIO_ACCOUNT_SID": "AC00000000000000000000000000000000",
    "VOXSTATE_TWILIO_AUTH_TOKEN": "twilio-secret",
    "VOXSTATE_TWILIO_PHONE_NUMBER": "+15555550100",
    "VOXSTATE_CARTESIA_API_KEY": "cartesia-secret",
    "VOXSTATE_CARTESIA_VOICE_ID": "00000000-0000-0000-0000-000000000001",
    "VOXSTATE_AWS_REGION": "us-east-1",
    "VOXSTATE_BEDROCK_MODEL_ID": "test-model",
    "VOXSTATE_PUBLIC_BASE_URL": "https://voxstate.example.com",
}


def set_valid_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in VALID_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)


def test_valid_configuration_is_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_valid_environment(monkeypatch)

    settings = Settings(_env_file=None)

    assert settings.runtime_mode is RuntimeMode.TEST
    assert settings.database_url.scheme == "postgresql"
    assert str(settings.supabase_url) == "https://example.supabase.co/"
    assert settings.twilio_phone_number == "+15555550100"
    assert settings.aws_region == "us-east-1"
    assert settings.bedrock_model_id == "test-model"
    assert settings.cartesia_voice_id == "00000000-0000-0000-0000-000000000001"


def test_runtime_mode_defaults_to_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_valid_environment(monkeypatch)
    monkeypatch.delenv("VOXSTATE_RUNTIME_MODE")

    settings = Settings(_env_file=None)

    assert settings.runtime_mode is RuntimeMode.DEVELOPMENT


def test_invalid_runtime_mode_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_valid_environment(monkeypatch)
    monkeypatch.setenv("VOXSTATE_RUNTIME_MODE", "invalid")

    with pytest.raises(ValidationError, match="runtime_mode"):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    ("environment_name", "field_name"),
    [
        ("VOXSTATE_DATABASE_URL", "database_url"),
        ("VOXSTATE_SUPABASE_URL", "supabase_url"),
        ("VOXSTATE_SUPABASE_SERVICE_ROLE_KEY", "supabase_service_role_key"),
        ("VOXSTATE_TWILIO_ACCOUNT_SID", "twilio_account_sid"),
        ("VOXSTATE_TWILIO_AUTH_TOKEN", "twilio_auth_token"),
        ("VOXSTATE_TWILIO_PHONE_NUMBER", "twilio_phone_number"),
        ("VOXSTATE_CARTESIA_API_KEY", "cartesia_api_key"),
        ("VOXSTATE_CARTESIA_VOICE_ID", "cartesia_voice_id"),
        ("VOXSTATE_AWS_REGION", "aws_region"),
        ("VOXSTATE_BEDROCK_MODEL_ID", "bedrock_model_id"),
        ("VOXSTATE_PUBLIC_BASE_URL", "public_base_url"),
    ],
)
def test_required_configuration_is_rejected_when_missing(
    monkeypatch: pytest.MonkeyPatch,
    environment_name: str,
    field_name: str,
) -> None:
    set_valid_environment(monkeypatch)
    monkeypatch.delenv(environment_name)

    with pytest.raises(ValidationError, match=field_name):
        Settings(_env_file=None)


def test_invalid_database_url_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_valid_environment(monkeypatch)
    monkeypatch.setenv("VOXSTATE_DATABASE_URL", "not-a-postgres-url")

    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)


def test_secrets_are_hidden_from_representation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_valid_environment(monkeypatch)

    rendered_settings = repr(Settings(_env_file=None))

    assert "supabase-secret" not in rendered_settings
    assert "twilio-secret" not in rendered_settings
    assert "cartesia-secret" not in rendered_settings
    assert "**********" in rendered_settings


def test_production_configuration_is_rejected_during_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_valid_environment(monkeypatch)
    monkeypatch.setenv("VOXSTATE_RUNTIME_MODE", "production")

    with pytest.raises(
        ValidationError,
        match="Production configuration cannot be loaded",
    ):
        Settings(_env_file=None)


def test_invalid_twilio_phone_number_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_valid_environment(monkeypatch)
    monkeypatch.setenv("VOXSTATE_TWILIO_PHONE_NUMBER", "555-1234")

    with pytest.raises(ValidationError, match="twilio_phone_number"):
        Settings(_env_file=None)


def test_placeholder_public_tunnel_is_rejected_outside_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_valid_environment(monkeypatch)
    monkeypatch.setenv("VOXSTATE_RUNTIME_MODE", "development")
    monkeypatch.setenv(
        "VOXSTATE_PUBLIC_BASE_URL",
        "https://your-public-tunnel.example",
    )

    with pytest.raises(ValidationError, match="public_base_url"):
        Settings(_env_file=None)
