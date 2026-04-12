from typing import Literal

from pydantic import BaseModel, ConfigDict


class DropboxCredentials(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: Literal["dropbox"]
    version: str
    refresh_token: str
    expires_at: str | None = None


class OpenAICredentials(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: Literal["openai"]
    version: str
    api_key: str


class TelegramCredentials(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: Literal["telegram"]
    version: str
    bot_token: str


class SMTPCredentials(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: Literal["smtp"]
    version: str
    password: str


class ManagedStorageCredentials(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: Literal["managed"]
    version: str
    access_key_id: str
    secret_access_key: str
    endpoint_url: str
    bucket: str
    region: str = "auto"


CredentialPayload = (
    DropboxCredentials | OpenAICredentials | TelegramCredentials | SMTPCredentials | ManagedStorageCredentials
)
