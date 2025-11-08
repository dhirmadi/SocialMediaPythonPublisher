from __future__ import annotations

import smtplib
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
import asyncio

from publisher_v2.config.schema import EmailConfig
from publisher_v2.core.models import PublishResult
from publisher_v2.services.publishers.base import Publisher


class EmailPublisher(Publisher):
    def __init__(self, config: Optional[EmailConfig], enabled: bool):
        self._config = config
        self._enabled = enabled and config is not None

    @property
    def platform_name(self) -> str:
        return "email"

    def is_enabled(self) -> bool:
        return self._enabled

    async def publish(self, image_path: str, caption: str) -> PublishResult:
        if not self._enabled or not self._config:
            return PublishResult(success=False, platform=self.platform_name, error="Disabled or not configured")
        try:
            def _send() -> None:
                msg = MIMEMultipart()
                msg["Subject"] = caption[:50]
                msg["From"] = self._config.sender
                msg["To"] = self._config.recipient
                msg.attach(MIMEText(caption))
                with open(image_path, "rb") as f:
                    img = MIMEImage(f.read())
                    img.add_header("Content-Disposition", "attachment", filename=image_path.split("/")[-1])
                    msg.attach(img)
                server = smtplib.SMTP(self._config.smtp_server, self._config.smtp_port, timeout=30)
                server.starttls()
                server.login(self._config.sender, self._config.password)
                server.sendmail(self._config.sender, [self._config.recipient], msg.as_string())
                server.quit()

            await asyncio.to_thread(_send)
            return PublishResult(success=True, platform=self.platform_name)
        except Exception as exc:
            return PublishResult(success=False, platform=self.platform_name, error=str(exc))


