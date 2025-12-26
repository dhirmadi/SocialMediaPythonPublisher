from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict


class DropboxCredentials(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: Literal["dropbox"]
    version: str
    refresh_token: str
    expires_at: Optional[str] = None


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


CredentialPayload = Union[DropboxCredentials, OpenAICredentials, TelegramCredentials, SMTPCredentials]


