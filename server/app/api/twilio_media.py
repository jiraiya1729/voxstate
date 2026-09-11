from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.api.dependencies import (
    get_media_session_service,
    get_twilio_webhook_verifier,
)
from app.calls.lifecycle import ProviderCallMismatchError
from app.voice.errors import VoiceRuntimeError
from app.voice.media_messages import (
    ConnectedMessage,
    MalformedMediaMessage,
    MediaMessage,
    StartMessage,
    StopMessage,
    build_outbound_media_message,
    parse_media_message,
)
from app.voice.sessions import MediaSessionError, MediaSessionService
from app.voice.twilio import TwilioWebhookVerifier

router = APIRouter(tags=["twilio-media"])

POLICY_VIOLATION = 1008
UNSUPPORTED_DATA = 1003

INTERNAL_ERROR = 1011


@router.websocket("/media/twilio")
async def receive_twilio_media(
    websocket: WebSocket,
    service: Annotated[
        MediaSessionService,
        Depends(get_media_session_service),
    ],
    verifier: Annotated[
        TwilioWebhookVerifier,
        Depends(get_twilio_webhook_verifier),
    ],
) -> None:
    signature = websocket.headers.get("X-Twilio-Signature")
    if signature is None or not verifier.validate_media_stream(signature=signature):
        await websocket.close(code=POLICY_VIOLATION)
        return

    await websocket.accept()
    connected = False
    active_stream_sid: str | None = None

    try:
        while True:
            message = parse_media_message(await websocket.receive_text())

            if isinstance(message, ConnectedMessage):
                if connected or active_stream_sid is not None:
                    raise MalformedMediaMessage("duplicate connected message")
                connected = True
                continue

            if isinstance(message, StartMessage):
                if not connected or active_stream_sid is not None:
                    raise MalformedMediaMessage("start message is out of order")
                stream_sid = message.stream_sid

                async def send_audio(
                    audio: bytes,
                    _stream_sid: str = stream_sid,
                ) -> None:
                    await websocket.send_json(
                        build_outbound_media_message(_stream_sid, audio)
                    )

                session = await service.start(message, audio_sink=send_audio)
                active_stream_sid = session.stream_sid
                continue

            if isinstance(message, MediaMessage):
                if active_stream_sid != message.stream_sid:
                    raise MediaSessionError("media references an unknown stream")
                await service.receive_media(message)
                continue

            if isinstance(message, StopMessage):
                if active_stream_sid != message.stream_sid:
                    raise MediaSessionError("stop references an unknown stream")
                await service.stop(message)
                active_stream_sid = None
                return
    except WebSocketDisconnect:
        pass
    except MalformedMediaMessage:
        await websocket.close(code=UNSUPPORTED_DATA)
    except VoiceRuntimeError:
        await websocket.close(code=INTERNAL_ERROR)
    except (MediaSessionError, ProviderCallMismatchError):
        await websocket.close(code=POLICY_VIOLATION)
    finally:
        await service.disconnect(active_stream_sid)
