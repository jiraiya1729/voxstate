"""Pure call lifecycle rules.

This file normalizes provider statuses and decides whether a status callback is legal,
duplicate, stale, terminal, or unsupported.
"""

from enum import StrEnum


class CallStatus(StrEnum):
    """Internal call lifecycle states normalized from provider statuses."""

    PENDING = "pending"
    QUEUED = "queued"
    INITIATED = "initiated"
    RINGING = "ringing"
    IN_PROGRESS = "in-progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BUSY = "busy"
    NO_ANSWER = "no-answer"


TERMINAL_STATUSES = {
    CallStatus.COMPLETED,
    CallStatus.FAILED,
    CallStatus.BUSY,
    CallStatus.NO_ANSWER,
}

NON_TERMINAL_ORDER = {
    CallStatus.PENDING: 0,
    CallStatus.QUEUED: 1,
    CallStatus.INITIATED: 2,
    CallStatus.RINGING: 3,
    CallStatus.IN_PROGRESS: 4,
}

PROVIDER_STATUS_MAP = {
    "queued": CallStatus.QUEUED,
    "initiated": CallStatus.INITIATED,
    "ringing": CallStatus.RINGING,
    "answered": CallStatus.IN_PROGRESS,
    "in-progress": CallStatus.IN_PROGRESS,
    "completed": CallStatus.COMPLETED,
    "failed": CallStatus.FAILED,
    "busy": CallStatus.BUSY,
    "no-answer": CallStatus.NO_ANSWER,
}


class UnsupportedProviderStatus(ValueError):
    pass


class UnknownCallError(LookupError):
    pass


class ProviderCallMismatchError(ValueError):
    pass


def normalize_provider_status(provider_status: str) -> CallStatus:
    """Convert a Twilio/provider status string into an internal CallStatus."""
    try:
        return PROVIDER_STATUS_MAP[provider_status.strip().lower()]
    except KeyError as exc:
        raise UnsupportedProviderStatus(provider_status) from exc


def resolve_call_transition(
    current_status: str, provider_status: str
) -> CallStatus | None:
    """Return the next legal status, or None for duplicate/stale callbacks."""
    current = CallStatus(current_status)
    target = normalize_provider_status(provider_status)

    if current == target:
        return None

    if current in TERMINAL_STATUSES:
        return None

    if target in TERMINAL_STATUSES:
        return target

    if NON_TERMINAL_ORDER[target] <= NON_TERMINAL_ORDER[current]:
        return None

    return target
