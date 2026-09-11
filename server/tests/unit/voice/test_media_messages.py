import json

import pytest

from app.voice.media_messages import (
    MalformedMediaMessage,
    MediaMessage,
    StartMessage,
    build_outbound_media_message,
    parse_media_message,
)


def test_outbound_media_message_base64_encodes_audio() -> None:
    assert build_outbound_media_message("MZ0001", b"\x01\x02\x03") == {
        "event": "media",
        "streamSid": "MZ0001",
        "media": {"payload": "AQID"},
    }


def test_start_message_is_typed() -> None:
    message = parse_media_message(
        json.dumps(
            {
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
                    "customParameters": {"call_id": "internal-id"},
                },
            }
        )
    )

    assert isinstance(message, StartMessage)
    assert message.sequence_number == 1
    assert message.start.media_format.sample_rate == 8000


def test_media_payload_is_decoded() -> None:
    message = parse_media_message(
        json.dumps(
            {
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
        )
    )

    assert isinstance(message, MediaMessage)
    assert message.media.decoded_audio() == b"\x01\x02\x03"


@pytest.mark.parametrize(
    "raw_message",
    [
        "not-json",
        '{"event":"unknown"}',
        '{"event":"media","streamSid":"MZ0001"}',
    ],
)
def test_malformed_or_unknown_message_is_rejected(raw_message: str) -> None:
    with pytest.raises(MalformedMediaMessage):
        parse_media_message(raw_message)


def test_invalid_base64_audio_is_rejected() -> None:
    message = parse_media_message(
        json.dumps(
            {
                "event": "media",
                "sequenceNumber": "2",
                "streamSid": "MZ0001",
                "media": {
                    "track": "inbound",
                    "chunk": "1",
                    "timestamp": "0",
                    "payload": "%%%",
                },
            }
        )
    )

    assert isinstance(message, MediaMessage)
    with pytest.raises(MalformedMediaMessage):
        message.media.decoded_audio()
