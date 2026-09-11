import json
from collections.abc import Awaitable, Callable
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.dependencies import (
    get_media_session_service,
    get_twilio_webhook_verifier,
)
from app.main import create_app
from app.voice.response import ModelProviderError


class StubVerifier:
    def __init__(self, valid: bool) -> None:
        self.valid = valid

    def validate_media_stream(self, *, signature: str) -> bool:
        return self.valid


class RecordingMediaService:
    def __init__(self) -> None:
        self.started = 0
        self.media = 0
        self.stopped = 0
        self.disconnects: list[str | None] = []
        self.audio_sink: Callable[[bytes], Awaitable[None]] | None = None

    async def start(
        self,
        message: object,
        *,
        audio_sink: Callable[[bytes], Awaitable[None]],
    ) -> SimpleNamespace:
        self.started += 1
        self.audio_sink = audio_sink
        return SimpleNamespace(stream_sid="MZ0001")

    async def receive_media(self, message: object) -> None:
        self.media += 1

    async def stop(self, message: object) -> bool:
        self.stopped += 1
        return True

    async def disconnect(self, stream_sid: str | None) -> bool:
        self.disconnects.append(stream_sid)
        return False


class FailingModelMediaService(RecordingMediaService):
    async def receive_media(self, message: object) -> None:
        raise ModelProviderError("Bedrock failed")


class PlaybackMediaService(RecordingMediaService):
    async def receive_media(self, message: object) -> None:
        await super().receive_media(message)
        assert self.audio_sink is not None
        await self.audio_sink(b"\x7f\x80")


CONNECTED = {
    "event": "connected",
    "protocol": "Call",
    "version": "1.0.0",
}
START = {
    "event": "start",
    "sequenceNumber": "1",
    "streamSid": "MZ0001",
    "start": {
        "accountSid": "AC0001",
        "streamSid": "MZ0001",
        "callSid": "CA0001",
        "tracks": ["inbound"],
        "mediaFormat": {
            "encoding": "audio/x-mulaw",
            "sampleRate": 8000,
            "channels": 1,
        },
        "customParameters": {"call_id": "00000000-0000-0000-0000-000000000001"},
    },
}
MEDIA = {
    "event": "media",
    "sequenceNumber": "2",
    "streamSid": "MZ0001",
    "media": {
        "track": "inbound",
        "chunk": "1",
        "timestamp": "0",
        "payload": "AQID",
    },
}
STOP = {
    "event": "stop",
    "sequenceNumber": "3",
    "streamSid": "MZ0001",
    "stop": {"accountSid": "AC0001", "callSid": "CA0001"},
}


def create_test_app(service: RecordingMediaService, valid: bool = True):
    app = create_app()
    app.dependency_overrides[get_media_session_service] = lambda: service
    app.dependency_overrides[get_twilio_webhook_verifier] = lambda: StubVerifier(valid)
    return app


def test_complete_websocket_sequence_is_dispatched() -> None:
    service = RecordingMediaService()
    app = create_test_app(service)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/media/twilio",
            headers={"X-Twilio-Signature": "valid"},
        ) as websocket:
            websocket.send_text(json.dumps(CONNECTED))
            websocket.send_text(json.dumps(START))
            websocket.send_text(json.dumps(MEDIA))
            websocket.send_text(json.dumps(STOP))

    assert service.started == 1
    assert service.media == 1
    assert service.stopped == 1
    assert service.disconnects == [None]


def test_synthesized_audio_is_sent_to_twilio() -> None:
    service = PlaybackMediaService()
    app = create_test_app(service)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/media/twilio",
            headers={"X-Twilio-Signature": "valid"},
        ) as websocket:
            websocket.send_text(json.dumps(CONNECTED))
            websocket.send_text(json.dumps(START))
            websocket.send_text(json.dumps(MEDIA))

            assert websocket.receive_json() == {
                "event": "media",
                "streamSid": "MZ0001",
                "media": {"payload": "f4A="},
            }


def test_invalid_signature_rejects_handshake() -> None:
    service = RecordingMediaService()
    app = create_test_app(service, valid=False)

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as captured:
            with client.websocket_connect(
                "/media/twilio",
                headers={"X-Twilio-Signature": "invalid"},
            ):
                pass

    assert captured.value.code == 1008
    assert service.started == 0


def test_media_before_start_closes_connection() -> None:
    service = RecordingMediaService()
    app = create_test_app(service)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/media/twilio",
            headers={"X-Twilio-Signature": "valid"},
        ) as websocket:
            websocket.send_text(json.dumps(CONNECTED))
            websocket.send_text(json.dumps(MEDIA))
            with pytest.raises(WebSocketDisconnect) as captured:
                websocket.receive_text()

    assert captured.value.code == 1008
    assert service.media == 0


def test_malformed_frame_closes_connection() -> None:
    service = RecordingMediaService()
    app = create_test_app(service)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/media/twilio",
            headers={"X-Twilio-Signature": "valid"},
        ) as websocket:
            websocket.send_text("not-json")
            with pytest.raises(WebSocketDisconnect) as captured:
                websocket.receive_text()

    assert captured.value.code == 1003


def test_model_failure_closes_connection_as_internal_error() -> None:
    service = FailingModelMediaService()
    app = create_test_app(service)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/media/twilio",
            headers={"X-Twilio-Signature": "valid"},
        ) as websocket:
            websocket.send_text(json.dumps(CONNECTED))
            websocket.send_text(json.dumps(START))
            websocket.send_text(json.dumps(MEDIA))
            with pytest.raises(WebSocketDisconnect) as captured:
                websocket.receive_text()

    assert captured.value.code == 1011
    assert service.disconnects == ["MZ0001"]
