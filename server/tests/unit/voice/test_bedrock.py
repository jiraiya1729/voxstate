import time
from typing import Any

import pytest

from app.voice.conversation.response import (
    EmptyModelInputError,
    Message,
    MessageRole,
    ModelProviderError,
    ModelResponseError,
    ModelTimeoutError,
)
from app.voice.providers.bedrock import BedrockLanguageModel


class RecordingBedrockClient:
    def __init__(self, response: object) -> None:
        self.response = response
        self.requests: list[dict[str, Any]] = []

    def converse(self, **kwargs: Any) -> object:
        self.requests.append(kwargs)
        return self.response


@pytest.mark.asyncio
async def test_bedrock_receives_system_prompt_and_ordered_messages() -> None:
    client = RecordingBedrockClient(
        {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"text": "I can help with that."}],
                }
            }
        }
    )
    model = BedrockLanguageModel(
        client=client,
        model_id="test-model",
        timeout_seconds=1.0,
    )
    messages = (
        Message(role=MessageRole.USER, text="Hello"),
        Message(role=MessageRole.ASSISTANT, text="Hi"),
        Message(role=MessageRole.USER, text="Please help"),
    )

    response = await model.generate(
        system_prompt="Keep the answer brief.",
        messages=messages,
    )

    assert response == "I can help with that."
    assert client.requests == [
        {
            "modelId": "test-model",
            "system": [{"text": "Keep the answer brief."}],
            "messages": [
                {"role": "user", "content": [{"text": "Hello"}]},
                {"role": "assistant", "content": [{"text": "Hi"}]},
                {"role": "user", "content": [{"text": "Please help"}]},
            ],
            "inferenceConfig": {
                "maxTokens": 256,
                "temperature": 0.2,
            },
        }
    ]


@pytest.mark.asyncio
async def test_multiple_text_blocks_are_joined_in_order() -> None:
    client = RecordingBedrockClient(
        {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"text": "Hello "}, {"text": "there."}],
                }
            }
        }
    )
    model = BedrockLanguageModel(
        client=client,
        model_id="test-model",
        timeout_seconds=1.0,
    )

    response = await model.generate(
        system_prompt="Be concise.",
        messages=(Message(role=MessageRole.USER, text="Hello"),),
    )

    assert response == "Hello there."


@pytest.mark.asyncio
async def test_empty_message_history_is_rejected_before_provider_call() -> None:
    client = RecordingBedrockClient({})
    model = BedrockLanguageModel(
        client=client,
        model_id="test-model",
        timeout_seconds=1.0,
    )

    with pytest.raises(EmptyModelInputError):
        await model.generate(system_prompt="Be concise.", messages=())

    assert client.requests == []


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"output": {}},
        {"output": {"message": {"role": "user", "content": []}}},
        {"output": {"message": {"role": "assistant", "content": "bad"}}},
        {"output": {"message": {"role": "assistant", "content": [{}]}}},
    ],
)
@pytest.mark.asyncio
async def test_malformed_or_empty_response_is_rejected(response: object) -> None:
    client = RecordingBedrockClient(response)
    model = BedrockLanguageModel(
        client=client,
        model_id="test-model",
        timeout_seconds=1.0,
    )

    with pytest.raises(ModelResponseError):
        await model.generate(
            system_prompt="Be concise.",
            messages=(Message(role=MessageRole.USER, text="Hello"),),
        )


@pytest.mark.asyncio
async def test_provider_error_is_normalized() -> None:
    class FailingClient:
        def converse(self, **kwargs: Any) -> object:
            raise RuntimeError("provider unavailable")

    model = BedrockLanguageModel(
        client=FailingClient(),
        model_id="test-model",
        timeout_seconds=1.0,
    )

    with pytest.raises(ModelProviderError, match="Bedrock request failed"):
        await model.generate(
            system_prompt="Be concise.",
            messages=(Message(role=MessageRole.USER, text="Hello"),),
        )


@pytest.mark.asyncio
async def test_provider_timeout_is_normalized() -> None:
    class SlowClient:
        def converse(self, **kwargs: Any) -> object:
            time.sleep(0.05)
            return {}

    model = BedrockLanguageModel(
        client=SlowClient(),
        model_id="test-model",
        timeout_seconds=0.001,
    )

    with pytest.raises(ModelTimeoutError, match="timed out"):
        await model.generate(
            system_prompt="Be concise.",
            messages=(Message(role=MessageRole.USER, text="Hello"),),
        )
