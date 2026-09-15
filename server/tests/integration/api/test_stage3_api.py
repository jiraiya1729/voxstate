from uuid import UUID

from fastapi.testclient import TestClient

from app.api.dependencies import (
    get_inbound_call_service,
    get_transfer_service,
    get_twilio_webhook_verifier,
)
from app.calls.inbound import AcceptedInboundCall
from app.calls.transfers import TransferResult
from app.main import create_app

CALL_ID = UUID("00000000-0000-0000-0000-000000000301")
AGENT_ID = UUID("00000000-0000-0000-0000-000000000302")
TRANSFER_ID = UUID("00000000-0000-0000-0000-000000000303")


class Stage3Verifier:
    public_base_url = "https://voxstate.example.com"

    def validate_inbound_voice(self, **kwargs: object) -> bool:
        return True

    def validate_transfer_status(self, **kwargs: object) -> bool:
        return True


class RecordingInboundService:
    def __init__(self) -> None:
        self.inputs: list[dict[str, object]] = []

    async def accept(self, **kwargs: object) -> AcceptedInboundCall:
        self.inputs.append(kwargs)
        return AcceptedInboundCall(CALL_ID, AGENT_ID)


class RecordingTransferService:
    def __init__(self) -> None:
        self.agent_commands: list[dict[str, object]] = []
        self.human_commands: list[dict[str, object]] = []
        self.statuses: list[tuple[UUID, str]] = []

    async def transfer_to_agent(self, **kwargs: object) -> TransferResult:
        self.agent_commands.append(kwargs)
        return TransferResult(TRANSFER_ID, "completed", "agent")

    async def transfer_to_human(self, **kwargs: object) -> TransferResult:
        self.human_commands.append(kwargs)
        return TransferResult(TRANSFER_ID, "accepted", "human")

    async def apply_human_status(
        self, transfer_id: UUID, provider_status: str
    ) -> TransferResult:
        self.statuses.append((transfer_id, provider_status))
        return TransferResult(transfer_id, "completed", "human")


def test_signed_inbound_call_returns_correlated_media_twiml() -> None:
    inbound = RecordingInboundService()
    app = create_app()
    app.dependency_overrides[get_inbound_call_service] = lambda: inbound
    app.dependency_overrides[get_twilio_webhook_verifier] = Stage3Verifier
    with TestClient(app) as client:
        response = client.post(
            "/webhooks/twilio/voice",
            data={"CallSid": "CA301", "From": "+15555550301", "To": "+15555550302"},
            headers={"X-Twilio-Signature": "valid"},
        )
    assert response.status_code == 200
    assert f'value="{CALL_ID}"' in response.text
    assert inbound.inputs[0]["to_number"] == "+15555550302"


def test_transfer_commands_require_and_forward_idempotency_key() -> None:
    transfers = RecordingTransferService()
    app = create_app()
    app.dependency_overrides[get_transfer_service] = lambda: transfers
    with TestClient(app) as client:
        agent = client.post(
            f"/calls/{CALL_ID}/transfers/agent",
            json={"target_agent_id": str(AGENT_ID)},
            headers={"Idempotency-Key": "agent-command"},
        )
        human = client.post(
            f"/calls/{CALL_ID}/transfers/human",
            json={"to": "+15555550303"},
            headers={"Idempotency-Key": "human-command"},
        )
    assert agent.json()["status"] == "completed"
    assert human.json()["status"] == "accepted"
    assert transfers.agent_commands[0]["idempotency_key"] == "agent-command"
    assert transfers.human_commands[0]["idempotency_key"] == "human-command"


def test_signed_human_transfer_status_is_normalized() -> None:
    transfers = RecordingTransferService()
    app = create_app()
    app.dependency_overrides[get_transfer_service] = lambda: transfers
    app.dependency_overrides[get_twilio_webhook_verifier] = Stage3Verifier
    with TestClient(app) as client:
        response = client.post(
            f"/webhooks/twilio/transfers/{TRANSFER_ID}/status",
            data={"DialCallStatus": "completed"},
            headers={"X-Twilio-Signature": "valid"},
        )
    assert response.status_code == 204
    assert transfers.statuses == [(TRANSFER_ID, "completed")]
