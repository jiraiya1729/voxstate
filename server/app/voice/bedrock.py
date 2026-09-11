import asyncio
from collections.abc import Sequence
from typing import Any, Protocol

from app.voice.response import (
    EmptyModelInputError,
    Message,
    MessageRole,
    ModelProviderError,
    ModelResponseError,
    ModelTimeoutError,
)


class BedrockRuntimeClient(Protocol):
    def converse(self, **kwargs: Any) -> object: ...

    def close(self) -> None: ...


class BedrockLanguageModel:
    def __init__(
        self,
        *,
        client: BedrockRuntimeClient,
        model_id: str,
        timeout_seconds: float,
    ) -> None:
        self._client = client
        self._model_id = model_id
        self._timeout_seconds = timeout_seconds

    async def generate(
        self,
        *,
        system_prompt: str,
        messages: Sequence[Message],
    ) -> str:
        self._validate_input(system_prompt=system_prompt, messages=messages)

        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.converse,
                    modelId=self._model_id,
                    system=[{"text": system_prompt}],
                    messages=[
                        {
                            "role": message.role.value,
                            "content": [{"text": message.text}],
                        }
                        for message in messages
                    ],
                    inferenceConfig={
                        "maxTokens": 256,
                        "temperature": 0.2,
                    },
                ),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as exc:
            raise ModelTimeoutError("Bedrock request timed out") from exc
        except Exception as exc:
            raise ModelProviderError("Bedrock request failed") from exc

        return self._parse_response(response)

    @staticmethod
    def _validate_input(
        *,
        system_prompt: str,
        messages: Sequence[Message],
    ) -> None:
        if not system_prompt.strip():
            raise EmptyModelInputError("system prompt must not be empty")
        if not messages:
            raise EmptyModelInputError("conversation must not be empty")
        if any(not message.text.strip() for message in messages):
            raise EmptyModelInputError("conversation messages must not be empty")
        if messages[-1].role is not MessageRole.USER:
            raise EmptyModelInputError("conversation must end with a user message")

    @staticmethod
    def _parse_response(response: object) -> str:
        if not isinstance(response, dict):
            raise ModelResponseError("Bedrock returned a malformed response")

        output = response.get("output")
        if not isinstance(output, dict):
            raise ModelResponseError("Bedrock response is missing output")

        message = output.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise ModelResponseError("Bedrock response is missing assistant message")

        content = message.get("content")
        if not isinstance(content, list):
            raise ModelResponseError("Bedrock assistant content is malformed")

        text_parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    text_parts.append(text)

        response_text = "".join(text_parts).strip()
        if not response_text:
            raise ModelResponseError("Bedrock returned empty assistant text")
        return response_text
