from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.schemas import AgentCreate, RoutingRuleCreate


def valid_agent() -> dict[str, object]:
    return {
        "name": "Support",
        "system_prompt": "Help the caller.",
        "language": "en-US",
        "bedrock_model_id": "model.example",
        "cartesia_voice_id": "voice-example",
    }


def test_agent_configuration_is_normalized() -> None:
    agent = AgentCreate.model_validate({**valid_agent(), "name": "  Support  "})
    assert agent.name == "Support"
    assert agent.bedrock_timeout_seconds == 20.0
    assert agent.cartesia_tts_model_id == "sonic-latest"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", " "),
        ("system_prompt", ""),
        ("language", "english_US"),
        ("bedrock_timeout_seconds", 0),
    ],
)
def test_agent_configuration_rejects_invalid_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        AgentCreate.model_validate({**valid_agent(), field: value})


def test_routing_rule_requires_a_signal() -> None:
    with pytest.raises(ValidationError, match="routing signal"):
        RoutingRuleCreate(agent_id=uuid4())
