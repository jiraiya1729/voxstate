from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from app.voice.runtime import AgentRuntimeFactory


def test_runtime_factory_uses_agent_specific_configuration() -> None:
    bedrock = Mock()
    cartesia = Mock()
    factory = AgentRuntimeFactory(bedrock_client=bedrock, cartesia_client=cartesia)
    agent = SimpleNamespace(
        id=uuid4(),
        system_prompt="Billing prompt",
        language="es",
        bedrock_model_id="billing-model",
        bedrock_timeout_seconds=9.0,
        cartesia_voice_id="billing-voice",
        cartesia_tts_model_id="sonic-latest",
    )
    runtime = factory.build(agent)
    assert runtime.system_prompt == "Billing prompt"
    assert runtime.language_model._model_id == "billing-model"
    assert runtime.language_model._timeout_seconds == 9.0
    assert runtime.speech_synthesizer._voice_id == "billing-voice"
    assert runtime.speech_synthesizer._language == "es"
