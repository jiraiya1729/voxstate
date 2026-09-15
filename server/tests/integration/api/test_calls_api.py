from uuid import UUID

from fastapi.testclient import TestClient

from app.api.dependencies import get_call_service
from app.calls.outbound import CallInitiationFailed, InitiatedCall
from app.main import create_app

CALL_ID = UUID("00000000-0000-0000-0000-000000000001")
PROVIDER_CALL_ID = "CA00000000000000000000000000000001"


class SuccessfulCallService:
    def __init__(self) -> None:
        self.requested_numbers: list[str] = []

    async def initiate_call(self, to_number: str, agent_id: UUID) -> InitiatedCall:
        self.requested_numbers.append(to_number)
        return InitiatedCall(
            id=CALL_ID,
            status="queued",
            provider_call_id=PROVIDER_CALL_ID,
            agent_id=agent_id,
        )


class FailedCallService:
    async def initiate_call(self, to_number: str, agent_id: UUID) -> InitiatedCall:
        raise CallInitiationFailed(
            call_id=CALL_ID,
            provider_code="21211",
        )


def test_create_call_returns_queued_call() -> None:
    service = SuccessfulCallService()
    app = create_app()
    app.dependency_overrides[get_call_service] = lambda: service

    with TestClient(app) as client:
        response = client.post(
            "/calls",
            json={"to": "+15555550112", "agent_id": str(CALL_ID)},
        )

    assert response.status_code == 201
    assert response.json() == {
        "id": str(CALL_ID),
        "status": "queued",
        "provider_call_id": PROVIDER_CALL_ID,
        "agent_id": str(CALL_ID),
    }
    assert service.requested_numbers == ["+15555550112"]


def test_create_call_rejects_invalid_e164_number() -> None:
    app = create_app()
    app.dependency_overrides[get_call_service] = SuccessfulCallService

    with TestClient(app) as client:
        response = client.post(
            "/calls",
            json={"to": "555-1234", "agent_id": str(CALL_ID)},
        )

    assert response.status_code == 422


def test_create_call_maps_provider_failure_to_bad_gateway() -> None:
    app = create_app()
    app.dependency_overrides[get_call_service] = FailedCallService

    with TestClient(app) as client:
        response = client.post(
            "/calls",
            json={"to": "+15555550113", "agent_id": str(CALL_ID)},
        )

    assert response.status_code == 502
    assert response.json() == {
        "detail": {
            "code": "telephony_provider_error",
            "call_id": str(CALL_ID),
            "provider_code": "21211",
        }
    }
