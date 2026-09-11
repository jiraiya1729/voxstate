from uuid import UUID

from fastapi.testclient import TestClient

from app.api.dependencies import (
    get_call_lifecycle_service,
    get_twilio_webhook_verifier,
)
from app.main import create_app

CALL_ID = UUID("00000000-0000-0000-0000-000000000001")


class StubVerifier:
    def __init__(self, valid: bool) -> None:
        self.valid = valid

    def validate(self, **kwargs: object) -> bool:
        return self.valid


class RecordingLifecycleService:
    def __init__(self) -> None:
        self.callbacks: list[dict[str, object]] = []

    async def apply_status_callback(self, **kwargs: object) -> str:
        self.callbacks.append(kwargs)
        return "ringing"


def test_valid_signed_callback_is_applied() -> None:
    lifecycle = RecordingLifecycleService()
    app = create_app()
    app.dependency_overrides[get_call_lifecycle_service] = lambda: lifecycle
    app.dependency_overrides[get_twilio_webhook_verifier] = lambda: StubVerifier(True)

    with TestClient(app) as client:
        response = client.post(
            f"/webhooks/twilio/calls/{CALL_ID}/status",
            data={
                "CallSid": "CA00000000000000000000000000000001",
                "CallStatus": "ringing",
            },
            headers={"X-Twilio-Signature": "valid"},
        )

    assert response.status_code == 204
    assert lifecycle.callbacks == [
        {
            "call_id": CALL_ID,
            "provider_call_id": "CA00000000000000000000000000000001",
            "provider_status": "ringing",
        }
    ]


def test_invalid_signature_is_rejected_before_lifecycle_processing() -> None:
    lifecycle = RecordingLifecycleService()
    app = create_app()
    app.dependency_overrides[get_call_lifecycle_service] = lambda: lifecycle
    app.dependency_overrides[get_twilio_webhook_verifier] = lambda: StubVerifier(False)

    with TestClient(app) as client:
        response = client.post(
            f"/webhooks/twilio/calls/{CALL_ID}/status",
            data={
                "CallSid": "CA00000000000000000000000000000001",
                "CallStatus": "ringing",
            },
            headers={"X-Twilio-Signature": "invalid"},
        )

    assert response.status_code == 403
    assert lifecycle.callbacks == []


def test_missing_required_provider_field_is_rejected() -> None:
    app = create_app()
    app.dependency_overrides[get_call_lifecycle_service] = RecordingLifecycleService
    app.dependency_overrides[get_twilio_webhook_verifier] = lambda: StubVerifier(True)

    with TestClient(app) as client:
        response = client.post(
            f"/webhooks/twilio/calls/{CALL_ID}/status",
            data={"CallSid": "CA00000000000000000000000000000001"},
            headers={"X-Twilio-Signature": "valid"},
        )

    assert response.status_code == 422
