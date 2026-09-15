"""Per-agent runtime composition.

This file converts persisted agent configuration into live Bedrock language-model and
Cartesia speech-synthesizer adapters for a call session.
"""

from dataclasses import dataclass

from cartesia import AsyncCartesia

from app.agents.models import Agent
from app.voice.conversation.response import LanguageModel
from app.voice.conversation.synthesis import SpeechSynthesizer
from app.voice.providers.bedrock import BedrockLanguageModel, BedrockRuntimeClient
from app.voice.providers.cartesia_tts import CartesiaSpeechSynthesizer


@dataclass(frozen=True, slots=True)
class AgentRuntime:
    """Live voice components built from one persisted agent configuration."""

    system_prompt: str
    language_model: LanguageModel
    speech_synthesizer: SpeechSynthesizer


class AgentRuntimeFactory:
    """Builds per-agent LLM and TTS adapters using shared provider clients."""

    def __init__(
        self, *, bedrock_client: BedrockRuntimeClient, cartesia_client: AsyncCartesia
    ) -> None:
        self.bedrock_client = bedrock_client
        self.cartesia_client = cartesia_client

    def build(self, agent: Agent) -> AgentRuntime:
        """Convert a database Agent row into the runtime used by a live call."""
        return AgentRuntime(
            system_prompt=agent.system_prompt,
            language_model=BedrockLanguageModel(
                client=self.bedrock_client,
                model_id=agent.bedrock_model_id,
                timeout_seconds=agent.bedrock_timeout_seconds,
            ),
            speech_synthesizer=CartesiaSpeechSynthesizer(
                client=self.cartesia_client,
                voice_id=agent.cartesia_voice_id,
                model_id=agent.cartesia_tts_model_id,
                language=agent.language,
            ),
        )
