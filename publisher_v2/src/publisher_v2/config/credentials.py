"""Typed shapes for credential payloads resolved from the orchestrator.

Each model mirrors one provider's secret bundle as returned by
``POST /v1/credentials/resolve``. ``provider`` is the discriminator used to pick
the right member of ``CredentialPayload``, and ``version`` identifies which
stored revision of the secret was handed out, so a caller can detect rotation.
Extra fields are allowed so a newer orchestrator can add keys without breaking
older instances. Instances hold live secret material: never log or serialise
them into user-facing output.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class DropboxCredentials(BaseModel):
    """Dropbox OAuth secret bundle.

    ``refresh_token`` is long-lived and is exchanged for short-lived access
    tokens by the storage service. ``expires_at`` is an ISO-8601 timestamp for
    the refresh token itself when the grant is time-boxed, and ``None`` when it
    does not expire.
    """

    model_config = ConfigDict(extra="allow")

    provider: Literal["dropbox"]
    version: str
    refresh_token: str
    expires_at: str | None = None


class OpenAICredentials(BaseModel):
    """OpenAI API secret bundle used by the Vision/caption services."""

    model_config = ConfigDict(extra="allow")

    provider: Literal["openai"]
    version: str
    api_key: str


class TelegramCredentials(BaseModel):
    """Telegram Bot API secret bundle used by the Telegram publisher."""

    model_config = ConfigDict(extra="allow")

    provider: Literal["telegram"]
    version: str
    bot_token: str


class SMTPCredentials(BaseModel):
    """SMTP secret bundle for the email publisher.

    Carries the password only; host, port and username come from the non-secret
    runtime config rather than from the credential API.
    """

    model_config = ConfigDict(extra="allow")

    provider: Literal["smtp"]
    version: str
    password: str


class ManagedStorageCredentials(BaseModel):
    """S3-compatible secret bundle for orchestrator-managed (R2) storage.

    Combines the secret key pair with the non-secret addressing the client needs
    to reach the right bucket. ``region`` defaults to ``"auto"``, which is what
    R2 expects.
    """

    model_config = ConfigDict(extra="allow")

    provider: Literal["managed"]
    version: str
    access_key_id: str
    secret_access_key: str
    endpoint_url: str
    bucket: str
    region: str = "auto"


#: Discriminated union of every credential shape the orchestrator can return.
CredentialPayload = (
    DropboxCredentials | OpenAICredentials | TelegramCredentials | SMTPCredentials | ManagedStorageCredentials
)
