# Configuration — Social Media Publisher V2

Version: 2.0  
Last Updated: November 7, 2025

## 1. Environment (.env)
Required:
- DROPBOX_APP_KEY=...
- DROPBOX_APP_SECRET=...
- DROPBOX_REFRESH_TOKEN=...
- OPENAI_API_KEY=...

Optional:
- REPLICATE_API_TOKEN=...
- TELEGRAM_BOT_TOKEN=...
- TELEGRAM_CHANNEL_ID=...
- INSTA_PASSWORD=... (if using instagrapi)
- EMAIL_PASSWORD=... (Gmail app password)
- SMTP_SERVER="smtp.gmail.com"
- SMTP_PORT=587

## 2. INI Schema
```ini
[Dropbox]
image_folder = /Photos/to_post
archive = archive

[Content]
hashtag_string = #photography #portrait
archive = true
debug = false

[openAI]
model = gpt-4o-mini
system_prompt = You are a senior social media copywriter...
role_prompt = Write a caption for:

[Replicate]
model = andreasjansson/blip-2:f6...

[Instagram]
name = my_username

[Email]
sender = me@gmail.com
recipient = someone@example.com
smtp_server = smtp.gmail.com
smtp_port = 587
```

## 3. Validation Rules (pydantic)
- Dropbox folder must start with “/”
- OPENAI_API_KEY must start with “sk-”
- If Telegram enabled, both token and channel id are required
- SMTP port int in {25,465,587}; default 587
- archive/debug booleans parsed strictly


