from typing import Annotated

from pydantic import StringConstraints

E164number = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^\+[1-9]\d{7,14}$",
    ),
]
