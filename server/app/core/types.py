"""Shared typed value aliases used across API schemas and settings."""

from typing import Annotated

from pydantic import StringConstraints

E164number = Annotated[
    # Shared phone-number type for API payloads and settings.
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^\+[1-9]\d{7,14}$",
    ),
]
