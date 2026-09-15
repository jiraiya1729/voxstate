"""Provider-neutral telephony command contracts.

This file defines the small interface used by call services to start calls and transfer
live calls without depending directly on Twilio SDK types.
"""

from typing import Protocol
from uuid import UUID


class ProviderCall:
    """Normalized result returned after a telephony provider accepts a call command."""

    def __init__(self, provider_call_id: str) -> None:
        self.provider_call_id = provider_call_id


class TelephonyProviderError(Exception):
    """Provider command failure with a stable code safe to persist on a call."""

    def __init__(self, code: str) -> None:
        super().__init__("the telephony provider rejected the call request")
        self.code = code


class TelephonyGateway(Protocol):
    """Interface for outbound and transfer commands to telephony."""

    async def create_call(
        self,
        *,
        call_id: UUID,
        to_number: str,
    ) -> ProviderCall: ...

    async def transfer_call(
        self,
        *,
        provider_call_id: str,
        to_number: str,
        transfer_id: UUID,
    ) -> None: ...
