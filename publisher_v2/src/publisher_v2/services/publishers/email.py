import asyncio
import logging
import smtplib
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from publisher_v2.config.schema import EmailConfig
from publisher_v2.core.models import PublishResult
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.utils.captions import normalize_tags
from publisher_v2.utils.logging import log_publisher_publish, now_monotonic

logger = logging.getLogger("publisher_v2.publishers.email")


class EmailPublisher(Publisher):
    def __init__(self, config: EmailConfig | None, enabled: bool):
        self._config = config
        self._enabled = (
            enabled and config is not None and bool(config.sender) and bool(config.recipient) and bool(config.password)
        )

    @property
    def platform_name(self) -> str:
        return "email"

    def is_enabled(self) -> bool:
        return self._enabled

    async def publish(self, image_path: str, caption: str, context: dict | None = None) -> PublishResult:
        config = self._config
        if not self._enabled or not config:
            return PublishResult(success=False, platform=self.platform_name, error="Disabled or not configured")

        password = config.password
        if password is None:
            return PublishResult(success=False, platform=self.platform_name, error="Password not configured")

        start = now_monotonic()
        try:

            def _build_message(to_addr: str, subject: str, body: str) -> MIMEMultipart:
                msg = MIMEMultipart()
                msg["Subject"] = subject
                msg["From"] = config.sender
                msg["To"] = to_addr
                msg.attach(MIMEText(body, "plain", "utf-8"))
                with open(image_path, "rb") as f:
                    img = MIMEImage(f.read())
                    img.add_header("Content-Disposition", "attachment", filename=image_path.split("/")[-1])
                    msg.attach(img)
                return msg

            def _send_emails() -> None:
                # Connect once, send both emails, then quit
                server = smtplib.SMTP(config.smtp_server, config.smtp_port, timeout=30)
                server.starttls()
                server.login(config.sender, password)

                # Subject prefix per FetLife instructions
                prefix_map = {
                    "normal": "",
                    "private": "Private: ",
                    "avatar": "Avatar: ",
                }
                prefix = prefix_map.get((config.subject_mode or "normal").lower(), "")

                # Determine subject/body placement
                if config.caption_target.lower() == "subject" or config.caption_target.lower() == "both":
                    service_subject = f"{prefix}{caption}"
                    service_body = caption
                else:  # "body"
                    # Fallback subject when caption is in body only
                    service_subject = f"{prefix}Photo upload"
                    service_body = caption

                # Send to service (FetLife upload address)
                service_msg = _build_message(config.recipient, service_subject, service_body)
                server.sendmail(config.sender, [config.recipient], service_msg.as_string())

                # Optional confirmation back to sender
                if config.confirmation_to_sender:
                    analysis_tags: list = []
                    if context and isinstance(context.get("analysis_tags"), list):
                        analysis_tags = context.get("analysis_tags") or []
                    tags = normalize_tags(analysis_tags, config.confirmation_tags_count)
                    tags_line = (
                        f"Image Tags (FetLife context): {', '.join(tags)}"
                        if tags
                        else "Image Tags (FetLife context): (none)"
                    )
                    confirm_body = f"{service_body}\n\n---\n{tags_line}"
                    confirm_subject = service_subject
                    confirm_msg = _build_message(config.sender, confirm_subject, confirm_body)
                    server.sendmail(config.sender, [config.sender], confirm_msg.as_string())

                server.quit()

            await asyncio.to_thread(_send_emails)
            log_publisher_publish(logger, self.platform_name, start, success=True)
            return PublishResult(success=True, platform=self.platform_name)
        except Exception as exc:
            log_publisher_publish(logger, self.platform_name, start, success=False, error=str(exc))
            return PublishResult(success=False, platform=self.platform_name, error=str(exc))
