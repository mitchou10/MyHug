import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

TokenName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class AccessTokenIn(BaseModel):
    """A token to make. `write` includes `read`."""

    name: TokenName = Field(description="What it is for: `training job`, `my laptop`")
    scope: Literal["read", "write"] = "read"
    expires_in_days: int | None = Field(None, ge=1, le=365, description="Empty: it does not expire")


class AccessTokenOut(BaseModel):
    """A token as the list shows it: never the token itself."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    scope: Literal["read", "write"]
    # The first characters, to recognise it.
    prefix: str
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None


class CreatedAccessTokenOut(AccessTokenOut):
    """The answer to making a token, and the only time `token` is given: it cannot be read again."""

    token: str
