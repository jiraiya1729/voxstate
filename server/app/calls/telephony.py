from typing import Protocol
from uuid import UUID


class ProviderCall:
    def __init__(self, provider_call_id: str) -> None:
        self.provider_call_id = provider_call_id


class TelephonyProviderError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__("the telephony provider rejected the call request")
        self.code = code


class TelephonyGateway(Protocol):
    async def create_call(
        self,
        *,
        call_id: UUID,
        to_number: str,
    ) -> ProviderCall: ...
