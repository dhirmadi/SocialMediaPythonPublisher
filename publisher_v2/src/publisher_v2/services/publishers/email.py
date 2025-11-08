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

    async def publish(self, image_path: str, caption: str, context: Optional[dict] = None) -> PublishResult:
        if not self._enabled or not self._config:
            return PublishResult(success=False, platform=self.platform_name, error="Disabled or not configured")
        try:
            def _build_message(to_addr: str, subject: str, body: str) -> MIMEMultipart:
                msg = MIMEMultipart()
                msg["Subject"] = subject
                msg["From"] = self._config.sender
                msg["To"] = to_addr
                msg.attach(MIMEText(body))
                with open(image_path, "rb") as f:
                    img = MIMEImage(f.read())
                    img.add_header("Content-Disposition", "attachment", filename=image_path.split("/")[-1])
                    msg.attach(img)
                return msg

            def _normalize_tags(raw_tags: list[str], desired_count: int) -> list[str]:
                cleaned = []
                for t in raw_tags:
                    t = t.strip().lower().lstrip("#")
                    # Keep alphanumerics and spaces only; collapse spaces
                    t = "".join(ch if ch.isalnum() or ch == " " else " " for ch in t)
                    t = " ".join(t.split())
                    if t and t not in cleaned:
                        cleaned.append(t)
                return cleaned[: max(0, desired_count)]

            def _send_emails() -> None:
                # Connect once, send both emails, then quit
                server = smtplib.SMTP(self._config.smtp_server, self._config.smtp_port, timeout=30)
                server.starttls()
                server.login(self._config.sender, self._config.password)

                # Subject prefix per FetLife instructions
                prefix_map = {
                    "normal": "",
                    "private": "Private: ",
                    "avatar": "Avatar: ",
                }
                prefix = prefix_map.get((self._config.subject_mode or "normal").lower(), "")

                # Determine subject/body placement
                if self._config.caption_target.lower() == "subject":
                    service_subject = f"{prefix}{caption}"
                    service_body = caption
                elif self._config.caption_target.lower() == "both":
                    service_subject = f"{prefix}{caption}"
                    service_body = caption
                else:  # "body"
                    # Fallback subject when caption is in body only
                    service_subject = f"{prefix}Photo upload"
                    service_body = caption

                # Send to service (FetLife upload address)
                service_msg = _build_message(self._config.recipient, service_subject, service_body)
                server.sendmail(self._config.sender, [self._config.recipient], service_msg.as_string())

                # Optional confirmation back to sender
                if self._config.confirmation_to_sender:
                    analysis_tags = []
                    if context and isinstance(context.get("analysis_tags"), list):
                        analysis_tags = context.get("analysis_tags") or []
                    tags = _normalize_tags(analysis_tags, self._config.confirmation_tags_count)
                    tags_line = f"Image Tags (FetLife context): {', '.join(tags)}" if tags else "Image Tags (FetLife context): (none)"
                    confirm_body = f"{service_body}\n\n---\n{tags_line}"
                    confirm_subject = service_subject
                    confirm_msg = _build_message(self._config.sender, confirm_subject, confirm_body)
                    server.sendmail(self._config.sender, [self._config.sender], confirm_msg.as_string())

                server.quit()

            await asyncio.to_thread(_send_emails)
            return PublishResult(success=True, platform=self.platform_name)
        except Exception as exc:
            return PublishResult(success=False, platform=self.platform_name, error=str(exc))


