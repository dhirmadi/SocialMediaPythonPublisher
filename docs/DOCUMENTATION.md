# Social Media Python Publisher - Complete Documentation

**Version:** 1.0  
**Last Updated:** October 31, 2025  
**Status:** Active Development

---

## Table of Contents

1. [Overview](#1-overview)
2. [System Requirements](#2-system-requirements)
3. [Installation Guide](#3-installation-guide)
4. [Configuration](#4-configuration)
5. [Usage Guide](#5-usage-guide)
6. [API Reference](#6-api-reference)
7. [Architecture](#7-architecture)
8. [Troubleshooting](#8-troubleshooting)
9. [Advanced Topics](#9-advanced-topics)
10. [Support and Contribution](#support-and-contribution)

---

## 1. Overview

### 1.1 What is Social Media Python Publisher?

Social Media Python Publisher is an intelligent automation system designed to streamline content distribution across multiple social media platforms. It combines cloud storage, artificial intelligence, and social media APIs to create a seamless workflow for posting visual content.

### 1.2 Key Features

- **Intelligent Content Selection**: Randomly selects images from your Dropbox folder
- **AI-Powered Analysis**: Uses Replicate's BLIP-2 model to analyze image content and mood
- **Automated Caption Generation**: Leverages OpenAI GPT models to create engaging captions
- **Multi-Platform Distribution**: Simultaneously posts to Instagram, Telegram, and Email
- **Smart Archiving**: Automatically archives posted images to prevent duplication
- **Debug Mode**: Test functionality without affecting your production content
- **Session Management**: Maintains Instagram sessions for reliable authentication
- **Flexible Configuration**: Easy customization through INI files and environment variables

### 1.3 Workflow Overview

```
1. Random Image Selection from Dropbox
          ↓
2. Download Image Locally
          ↓
3. Generate Temporary Dropbox Link
          ↓
4. AI Analysis (Replicate BLIP-2)
   - Caption Generation
   - Mood Analysis
          ↓
5. OpenAI Caption Enhancement
          ↓
6. Multi-Platform Distribution
   ├─ Instagram (with session persistence)
   ├─ Telegram (with image resizing)
   └─ Email (Gmail SMTP)
          ↓
7. Archive Image (if successful)
```

### 1.4 Use Cases

- **Content Creators**: Automate daily posting schedules to maintain consistent presence
- **Photographers**: Share portfolio pieces across multiple platforms effortlessly
- **Small Businesses**: Maintain active social media profiles without manual intervention
- **Digital Marketers**: Streamline content distribution workflows
- **Personal Brands**: Build audience engagement with regular, AI-enhanced posts

---

## 2. System Requirements

### 2.1 Software Requirements

- **Python**: Version 3.7 or higher (3.9+ recommended)
- **Operating System**: Linux, macOS, or Windows with WSL
- **Internet Connection**: Required for API communications

### 2.2 Required API Accounts

| Service | Purpose | Cost | Sign-Up Link |
|---------|---------|------|--------------|
| Dropbox | Image storage and management | Free tier available (2GB) | [dropbox.com/developers](https://www.dropbox.com/developers) |
| OpenAI | Caption generation | Pay-as-you-go (~$0.50-1/month) | [platform.openai.com](https://platform.openai.com) |
| Replicate | Image analysis | Pay-as-you-go (~$1-2/month) | [replicate.com](https://replicate.com) |
| Telegram | Optional: Bot messaging | Free | [core.telegram.org/bots](https://core.telegram.org/bots) |
| Instagram | Optional: Photo posting | Free | Requires existing account |
| Gmail | Optional: Email distribution | Free | Requires app password |

### 2.3 Python Dependencies

```
dropbox >= 11.0.0        # Cloud storage integration
python-telegram-bot >= 13.0  # Telegram bot functionality
Pillow >= 8.0.0          # Image processing and resizing
configparser >= 5.0.0    # Configuration file parsing
instagrapi >= 2.0.0      # Instagram API wrapper
openai >= 1.7.2          # OpenAI API client
python-dotenv >= 1.0.0   # Environment variable management
replicate >= 0.22.0      # Replicate AI model integration
```

### 2.4 Disk Space Requirements

- **Application**: < 50 MB
- **Dependencies**: ~200 MB
- **Temporary Storage**: 50-100 MB per image (automatically cleaned)
- **Session Files**: < 1 MB

---

## 3. Installation Guide

### 3.1 Step 1: Clone Repository

```bash
git clone https://github.com/yourusername/SocialMediaPythonPublisher.git
cd SocialMediaPythonPublisher
```

### 3.2 Step 2: Set Up Python Environment

#### Option A: Using venv (Recommended)

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
# On Linux/macOS:
source venv/bin/activate
# On Windows:
venv\Scripts\activate
```

#### Option B: Using conda

```bash
conda create -n socialmedia python=3.9
conda activate socialmedia
```

### 3.3 Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### 3.4 Step 4: Configure Environment Variables

```bash
# Copy the example file
cp dotenv.example .env

# Edit with your favorite editor
nano .env  # or vim, code, etc.
```

#### Required Environment Variables:

```bash
# Dropbox Configuration
DROPBOX_APP_KEY="your_app_key_here"
DROPBOX_APP_PASSWORD="your_app_secret_here"
DROPBOX_REFRESH_TOKEN=""  # Will be auto-generated

# OpenAI Configuration
OPENAI_API_KEY="sk-your_openai_key_here"

# Replicate Configuration
REPLICATE_API_TOKEN="r8_your_replicate_token_here"

# Telegram Configuration (Optional)
TELEGRAM_BOT_TOKEN="your_bot_token_here"
TELEGRAM_CHANNEL_ID="@your_channel_or_chat_id"

# Instagram Configuration (Optional)
INSTA_PASSWORD="your_instagram_password"

# Email Configuration (Optional)
EMAIL_PASSWORD="your_gmail_app_password"
```

### 3.5 Step 5: Configure Application Settings

```bash
# Copy the example configuration
cp configfiles/SociaMediaConfig.ini.example configfiles/SocialMediaConfig.ini

# Edit configuration
nano configfiles/SocialMediaConfig.ini
```

#### Configuration Template:

```ini
[Email]
sender = your-email@gmail.com
recipient = recipient@example.com

[Instagram]
name = your_instagram_username

[Dropbox]
image_folder = /YourFolder/Images

[Content]
hashtag_string = #photography #art #creative
telegram = True
fetlife = False
instagram = True
archive = True
debug = False

[Replicate]
model = andreasjansson/blip-2:f677695e5e89f8b236e52ecd1d3f01beb44c34606419bcc19345e046d8f786f9

[openAI]
engine = gpt-3.5-turbo
systemcontent = You are an expert in social media focused on helping photographers getting more followers.
rolecontent = Write me a caption for a photograph that shows
```

### 3.6 Step 6: Authenticate with Dropbox

```bash
python py_db_auth.py .env
```

**Follow the prompts:**
1. Open the provided URL in your browser
2. Authorize the application
3. Copy the authorization code
4. Paste it into the terminal
5. Your `.env` file will be automatically updated with the refresh token

### 3.7 Step 7: Verify Installation

```bash
# Test with debug mode enabled
# First, set debug = True in your config file
python py_rotator_daily.py configfiles/SocialMediaConfig.ini
```

---

## 4. Configuration

### 4.1 Environment Variables (.env)

#### Dropbox Configuration

```bash
DROPBOX_APP_KEY="your_key"
```
- **Purpose**: Identifies your Dropbox application
- **How to Get**: Create an app at [Dropbox App Console](https://www.dropbox.com/developers/apps)
- **Required**: Yes

```bash
DROPBOX_APP_PASSWORD="your_secret"
```
- **Purpose**: Secret key for Dropbox authentication
- **How to Get**: Generated when you create the app
- **Required**: Yes

```bash
DROPBOX_REFRESH_TOKEN=""
```
- **Purpose**: Long-lived token for API access
- **How to Get**: Auto-generated by running `py_db_auth.py`
- **Required**: Yes (auto-filled)

#### OpenAI Configuration

```bash
OPENAI_API_KEY="sk-..."
```
- **Purpose**: Access OpenAI GPT models for caption generation
- **How to Get**: [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
- **Required**: Yes
- **Cost**: ~$0.50-1.00/month for typical usage

#### Replicate Configuration

```bash
REPLICATE_API_TOKEN="r8_..."
```
- **Purpose**: Access AI models for image analysis
- **How to Get**: [replicate.com/account](https://replicate.com/account)
- **Required**: Yes
- **Cost**: ~$1.00-2.00/month for typical usage

#### Telegram Configuration

```bash
TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."
```
- **Purpose**: Send messages via Telegram bot
- **How to Get**: Talk to [@BotFather](https://t.me/botfather) on Telegram
- **Required**: Only if `telegram = True`

```bash
TELEGRAM_CHANNEL_ID="@your_channel"
```
- **Purpose**: Target channel or chat for messages
- **Format**: `@channelname` or numeric chat ID
- **Required**: Only if `telegram = True`

#### Instagram Configuration

```bash
INSTA_PASSWORD="your_password"
```
- **Purpose**: Authenticate with Instagram
- **Security**: Store securely, never commit to version control
- **Required**: Only if `instagram = True`

#### Email Configuration

```bash
EMAIL_PASSWORD="your_app_password"
```
- **Purpose**: Send images via Gmail
- **How to Get**: Generate Gmail App Password in account settings
- **Required**: Only if `fetlife = True`

### 4.2 Application Settings (INI File)

#### [Email] Section

```ini
[Email]
sender = your-email@gmail.com
recipient = recipient@example.com
smtp_server = smtp.gmail.com
smtp_port = 587
```

- `sender`: Email address to send from
- `recipient`: Email address to receive images
- `smtp_server`: SMTP server address (default: smtp.gmail.com)
  - Gmail: `smtp.gmail.com`
  - Outlook/Office365: `smtp.office365.com`
  - Yahoo: `smtp.mail.yahoo.com`
  - Custom SMTP server: `your.smtp.server`
- `smtp_port`: SMTP port number (default: 587)
  - `587`: TLS (recommended, most common)
  - `465`: SSL (older, still supported)
  - `25`: Unencrypted (not recommended)

**Note**: Both `smtp_server` and `smtp_port` are optional. If not specified, the application defaults to Gmail settings (`smtp.gmail.com:587`)

#### [Instagram] Section

```ini
[Instagram]
name = your_username
```

- `name`: Your Instagram account username (without @)

#### [Dropbox] Section

```ini
[Dropbox]
image_folder = /MyImages/ToPost
```

- `image_folder`: Path in Dropbox where source images are stored
- **Note**: Case-sensitive, must start with `/`

#### [Content] Section

```ini
[Content]
hashtag_string = #photography #art #nature
telegram = True
fetlife = False
instagram = True
archive = True
debug = False
```

**Configuration Options:**

- `hashtag_string`: Hashtags appended to every post
- `telegram`: Enable/disable Telegram posting (True/False)
- `fetlife`: Enable/disable email posting (True/False)
- `instagram`: Enable/disable Instagram posting (True/False)
- `archive`: Archive images after successful posting (True/False)
- `debug`: Debug mode - posts but doesn't archive (True/False)

#### [Replicate] Section

```ini
[Replicate]
model = andreasjansson/blip-2:f677695e5e89f8b236e52ecd1d3f01beb44c34606419bcc19345e046d8f786f9
```

- `model`: Replicate model identifier for image analysis
- **Default**: BLIP-2 model (recommended)
- **Alternative**: You can use other vision-language models

#### [openAI] Section

```ini
[openAI]
engine = gpt-3.5-turbo
systemcontent = You are an expert in social media...
rolecontent = Write me a caption for a photograph that shows
```

**Configuration Options:**

- `engine`: OpenAI model to use (`gpt-3.5-turbo` or `gpt-4`)
- `systemcontent`: System prompt defining AI behavior
- `rolecontent`: User prompt prefix for caption generation

### 4.3 Configuration Examples

#### Example 1: Instagram Only

```ini
[Content]
telegram = False
fetlife = False
instagram = True
archive = True
debug = False
```

#### Example 2: Multi-Platform with Debug

```ini
[Content]
telegram = True
fetlife = True
instagram = True
archive = True
debug = True  # Won't actually archive
```

#### Example 3: Testing Configuration

```ini
[Content]
telegram = True
fetlife = False
instagram = False
archive = False
debug = True
```

---

## 5. Usage Guide

### 5.1 Basic Usage

#### Running the Application

```bash
python py_rotator_daily.py configfiles/SocialMediaConfig.ini
```

**Expected Output:**
```
INFO:root:Logged in via saved session
INFO:root:Email sent successfully to recipient@example.com
INFO:root:Image archived successfully.
```

### 5.2 Command-Line Arguments

#### Main Script: py_rotator_daily.py

```bash
python py_rotator_daily.py <config_file_path>
```

**Parameters:**
- `config_file_path`: Path to your INI configuration file

**Example:**
```bash
python py_rotator_daily.py configfiles/SocialMediaConfig.ini
```

#### Authentication Script: py_db_auth.py

```bash
python py_db_auth.py <env_file_path>
```

**Parameters:**
- `env_file_path`: Path to your .env file

**Example:**
```bash
python py_db_auth.py .env
```

### 5.3 Automation with Cron

#### Linux/macOS Cron Setup

```bash
# Edit crontab
crontab -e

# Add daily posting at 9 AM
0 9 * * * cd /path/to/SocialMediaPythonPublisher && /path/to/venv/bin/python py_rotator_daily.py configfiles/SocialMediaConfig.ini >> /var/log/socialmedia.log 2>&1

# Add posting three times daily (9 AM, 2 PM, 7 PM)
0 9,14,19 * * * cd /path/to/SocialMediaPythonPublisher && /path/to/venv/bin/python py_rotator_daily.py configfiles/SocialMediaConfig.ini
```

#### Windows Task Scheduler

1. Open Task Scheduler
2. Create Basic Task
3. Set Trigger (Daily at specific time)
4. Set Action: Start a Program
   - Program: `C:\path\to\python.exe`
   - Arguments: `py_rotator_daily.py configfiles/SocialMediaConfig.ini`
   - Start in: `C:\path\to\SocialMediaPythonPublisher`

### 5.4 Debug Mode

#### Enabling Debug Mode

Edit your configuration file:
```ini
[Content]
debug = True
```

#### What Debug Mode Does:

- ✅ Runs all posting operations
- ✅ Prints detailed console output
- ✅ Shows temporary Dropbox links
- ✅ Displays AI-generated content
- ❌ Does NOT archive images
- ❌ Does NOT remove images from source folder

#### Debug Output Example:

```
Temporary Dropbox Link: https://dl.dropboxusercontent.com/...
Image Summary: A serene landscape with mountains at sunset peaceful and inspiring
Message: Capturing the beauty of nature at its finest. The golden hour never disappoints. #photography #landscape
Sending Telegram: Capturing the beauty...
Sending Instagram: Capturing the beauty...
```

### 5.5 First Run Checklist

- [ ] `.env` file configured with all API keys
- [ ] `SocialMediaConfig.ini` configured with your preferences
- [ ] Dropbox authentication completed (`py_db_auth.py`)
- [ ] Images uploaded to Dropbox folder specified in config
- [ ] Archive folder created in Dropbox (`/YourFolder/Images/archive`)
- [ ] Debug mode enabled for first test
- [ ] Instagram username and password correct
- [ ] Telegram bot created and token obtained (if using)
- [ ] Gmail app password generated (if using email)

### 5.6 Workflow Best Practices

#### Image Preparation

1. **Format**: JPEG or PNG recommended
2. **Size**: Any size (will be resized for Telegram automatically)
3. **Naming**: Any naming convention works
4. **Organization**: Place all images in the configured Dropbox folder

#### Hashtag Strategy

```ini
# Good: Relevant, focused hashtags
hashtag_string = #photography #naturelovers #landscape

# Avoid: Too many hashtags (Instagram limit is 30)
hashtag_string = #tag1 #tag2 #tag3 ... #tag30  # Not recommended
```

#### Archive Management

The application automatically creates an `archive` subfolder in your image folder. Structure:

```
/YourFolder/Images/
  ├── image1.jpg  ← Active images
  ├── image2.jpg
  └── archive/
      ├── image3.jpg  ← Posted images
      └── image4.jpg
```

**Restoring Images:**
To repost an image, simply move it from `archive/` back to the parent folder.

---

## 6. API Reference

### 6.1 Core Functions - py_rotator_daily.py

#### read_config(configfile)

**Purpose**: Reads configuration from INI file and environment variables.

**Parameters:**
- `configfile` (str): Path to INI configuration file

**Returns:**
- `dict`: Configuration dictionary containing all settings

**Example:**
```python
config = read_config('configfiles/SocialMediaConfig.ini')
print(config['image_folder'])  # Output: /MyImages/ToPost
```

**Configuration Keys:**
```python
{
    'db_refresh': str,           # Dropbox refresh token
    'db_app': str,               # Dropbox app key
    'db_app_pw': str,            # Dropbox app password
    'bot_token': str,            # Telegram bot token
    'chat_id': str,              # Telegram chat/channel ID
    'image_folder': str,         # Dropbox image folder path
    'archive_folder': str,       # Archive folder name
    'instaname': str,            # Instagram username
    'instaword': str,            # Instagram password
    'email_recipient': str,      # Email recipient address
    'email_sender': str,         # Email sender address
    'email_password': str,       # Email password
    'hashtag_string': str,       # Hashtags to append
    'run_archive': bool,         # Archive after posting
    'run_telegram': bool,        # Enable Telegram
    'run_instagram': bool,       # Enable Instagram
    'run_fetlife': bool,         # Enable Email
    'run_debug': bool,           # Debug mode
    'openai_api_key': str,       # OpenAI API key
    'openai_engine': str,        # OpenAI model name
    'openai_systemcontent': str, # System prompt
    'openai_rolecontent': str,   # Role prompt
    'replicate_model': str       # Replicate model ID
}
```

---

#### query_openai(prompt, engine, api_key, systemcontent, rolecontent)

**Purpose**: Generates captions using OpenAI's GPT models.

**Parameters:**
- `prompt` (str): Image description from Replicate
- `engine` (str): OpenAI model (e.g., 'gpt-3.5-turbo')
- `api_key` (str): OpenAI API key
- `systemcontent` (str): System role prompt
- `rolecontent` (str): User role prompt prefix

**Returns:**
- `str`: Generated caption text
- `[]`: Empty list on error

**Example:**
```python
caption = query_openai(
    prompt="A sunset over mountains peaceful serene",
    engine="gpt-3.5-turbo",
    api_key="sk-...",
    systemcontent="You are a social media expert",
    rolecontent="Write a caption for:"
)
# Output: "Golden hour magic at its finest..."
```

**Error Handling:**
- Returns empty list `[]` on API errors
- Logs error messages to console

---

#### list_images_in_dropbox(dbx, path)

**Purpose**: Asynchronously lists all images in a Dropbox folder.

**Parameters:**
- `dbx` (dropbox.Dropbox): Authenticated Dropbox client
- `path` (str): Dropbox folder path

**Returns:**
- `list`: List of image filenames
- `[]`: Empty list on error

**Example:**
```python
images = await list_images_in_dropbox(dbx, '/MyImages')
print(images)  # Output: ['photo1.jpg', 'photo2.png']
```

**Notes:**
- Only returns file metadata, not folders
- Root path should be "" or "/"

---

#### download_image_from_dropbox(dbx, path, image_name)

**Purpose**: Asynchronously downloads an image from Dropbox to local temp folder.

**Parameters:**
- `dbx` (dropbox.Dropbox): Authenticated Dropbox client
- `path` (str): Dropbox folder path
- `image_name` (str): Name of image file

**Returns:**
- `str`: Local file path to downloaded image (`/tmp/image_name`)
- `None`: On download error

**Example:**
```python
local_file = await download_image_from_dropbox(dbx, '/MyImages', 'photo.jpg')
print(local_file)  # Output: /tmp/photo.jpg
```

**Notes:**
- Downloads to `/tmp/` directory
- File persists until manually deleted or system reboot

---

#### get_temp_link(dbx, path, image_name)

**Purpose**: Creates a temporary shareable link for a Dropbox file.

**Parameters:**
- `dbx` (dropbox.Dropbox): Authenticated Dropbox client
- `path` (str): Dropbox folder path
- `image_name` (str): Name of image file

**Returns:**
- `str`: Temporary download URL (valid for ~4 hours)
- `None`: On error

**Example:**
```python
link = get_temp_link(dbx, '/MyImages', 'photo.jpg')
print(link)  # Output: https://dl.dropboxusercontent.com/...
```

**Use Case:**
- Required for Replicate API (needs accessible URL)
- Links expire after approximately 4 hours

---

#### resize_image(image_file)

**Purpose**: Resizes image to maximum width of 1280px (for Telegram).

**Parameters:**
- `image_file` (str): Path to local image file

**Returns:**
- `str`: Path to resized image file (prefixed with `resized_`)

**Example:**
```python
resized = resize_image('/tmp/photo.jpg')
print(resized)  # Output: /tmp/resized_photo.jpg
```

**Behavior:**
- Maintains aspect ratio
- Uses Lanczos resampling for quality
- Only resizes if width > 1280px
- Saves as new file (original preserved)

---

#### archive_image(dbx, image_folder_path, selected_image_name, archive_folder_path)

**Purpose**: Moves posted image to archive folder in Dropbox.

**Parameters:**
- `dbx` (dropbox.Dropbox): Authenticated Dropbox client
- `image_folder_path` (str): Source folder path
- `selected_image_name` (str): Image filename
- `archive_folder_path` (str): Archive folder name (relative)

**Returns:**
- `None`

**Example:**
```python
archive_image(dbx, '/MyImages', 'photo.jpg', 'archive')
# Moves: /MyImages/photo.jpg → /MyImages/archive/photo.jpg
```

**Error Handling:**
- Logs errors but doesn't raise exceptions
- Creates archive folder if it doesn't exist

---

#### send_email(image_file, message, email_config)

**Purpose**: Asynchronously sends email with attached image via configurable SMTP server.

**Parameters:**
- `image_file` (str): Path to local image file
- `message` (str): Email body and subject text
- `email_config` (dict): Email configuration dictionary
  ```python
  {
      'email_sender': str,
      'email_recipient': str,
      'email_password': str,
      'smtp_server': str,      # SMTP server address
      'smtp_port': int         # SMTP port number
  }
  ```

**Returns:**
- `None`

**Example:**
```python
await send_email(
    '/tmp/photo.jpg',
    'Check out this amazing shot!',
    {
        'email_sender': 'sender@gmail.com',
        'email_recipient': 'recipient@example.com',
        'email_password': 'app_password',
        'smtp_server': 'smtp.gmail.com',
        'smtp_port': 587
    }
)
```

**Notes:**
- Uses configurable SMTP server (defaults to Gmail: smtp.gmail.com:587)
- Supports any SMTP server (Gmail, Outlook, Yahoo, custom)
- Requires App Password for most providers (not regular password)
- Image attached as MIME attachment
- Uses STARTTLS for secure connection

---

#### post_image_to_instagram(USERNAME, PASSWORD, image_path, caption)

**Purpose**: Asynchronously posts image to Instagram with caption.

**Parameters:**
- `USERNAME` (str): Instagram username
- `PASSWORD` (str): Instagram password
- `image_path` (str): Path to local image file
- `caption` (str): Post caption text

**Returns:**
- `None`

**Raises:**
- `Exception`: On login failure or posting error

**Example:**
```python
await post_image_to_instagram(
    'myusername',
    'mypassword',
    '/tmp/photo.jpg',
    'Beautiful sunset! #photography'
)
```

**Session Management:**
- Saves session to `instasession.json`
- Reuses session on subsequent runs
- Falls back to fresh login if session invalid

**Error Handling:**
- Logs warnings for session failures
- Raises exception on complete failure

---

#### send_telegram_message(bot_token, chat_id, image_file, message)

**Purpose**: Asynchronously sends image with caption to Telegram channel/chat.

**Parameters:**
- `bot_token` (str): Telegram bot API token
- `chat_id` (str): Target chat/channel ID
- `image_file` (str): Path to local image file
- `message` (str): Caption text (max 1024 characters)

**Returns:**
- `None`

**Example:**
```python
await send_telegram_message(
    '123456:ABC-DEF...',
    '@my_channel',
    '/tmp/resized_photo.jpg',
    'New post! #photography'
)
```

**Notes:**
- Caption limit: 1024 characters
- Image should be resized beforehand
- Supports both channels (@channel) and chats (numeric ID)

---

#### get_dropbox_client(configfile)

**Purpose**: Creates authenticated Dropbox client using refresh token.

**Parameters:**
- `configfile` (dict): Configuration dictionary with Dropbox credentials

**Returns:**
- `dropbox.Dropbox`: Authenticated Dropbox client instance

**Example:**
```python
config = read_config('config.ini')
dbx = get_dropbox_client(config)
```

**Authentication:**
- Uses OAuth2 refresh token (long-lived)
- Automatically refreshes access tokens as needed

---

### 6.2 Authentication Functions - py_db_auth.py

#### load_env(env_file)

**Purpose**: Loads environment variables from .env file.

**Parameters:**
- `env_file` (str): Path to .env file

**Returns:**
- `dict`: Dictionary of environment variables

**Example:**
```python
env = load_env('.env')
print(env['DROPBOX_APP_KEY'])
```

---

#### update_env(env_file, key, value)

**Purpose**: Updates or adds an environment variable to .env file.

**Parameters:**
- `env_file` (str): Path to .env file
- `key` (str): Variable name
- `value` (str): Variable value

**Returns:**
- `None`

**Example:**
```python
update_env('.env', 'DROPBOX_REFRESH_TOKEN', 'sl.ABC123...')
```

---

#### start_initial_auth(app_key, app_secret)

**Purpose**: Initiates Dropbox OAuth2 authentication flow.

**Parameters:**
- `app_key` (str): Dropbox app key
- `app_secret` (str): Dropbox app secret

**Returns:**
- `oauth_result`: OAuth result object containing refresh token

**Exits:**
- System exit on authentication failure

**Example:**
```python
result = start_initial_auth('your_key', 'your_secret')
print(result.refresh_token)
```

**Interactive Process:**
1. Prints authorization URL
2. Waits for user to visit URL and authorize
3. Prompts for authorization code
4. Exchanges code for refresh token

---

#### get_dropbox_client(app_key, app_secret, refresh_token)

**Purpose**: Creates Dropbox client with existing refresh token.

**Parameters:**
- `app_key` (str): Dropbox app key
- `app_secret` (str): Dropbox app secret
- `refresh_token` (str): OAuth2 refresh token

**Returns:**
- `dropbox.Dropbox`: Authenticated client

**Exits:**
- System exit on client creation failure

**Example:**
```python
dbx = get_dropbox_client('key', 'secret', 'refresh_token')
```

---

## 7. Architecture

### 7.1 System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   User Environment                       │
│  ┌──────────────┐         ┌──────────────┐             │
│  │ .env File    │         │ Config.ini   │             │
│  │ (Secrets)    │         │ (Settings)   │             │
│  └──────────────┘         └──────────────┘             │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│              py_rotator_daily.py (Main)                  │
│  ┌─────────────────────────────────────────────────┐   │
│  │  1. Configuration Loading                        │   │
│  │  2. Dropbox Client Initialization               │   │
│  │  3. Image Selection & Download                  │   │
│  │  4. AI Analysis (Replicate)                     │   │
│  │  5. Caption Generation (OpenAI)                 │   │
│  │  6. Multi-Platform Distribution                 │   │
│  │  7. Archiving                                   │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│                  External Services                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │ Dropbox  │  │ Replicate│  │ OpenAI   │             │
│  │ Storage  │  │ AI Model │  │ GPT      │             │
│  └──────────┘  └──────────┘  └──────────┘             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │Instagram │  │ Telegram │  │ Gmail    │             │
│  │ API      │  │ Bot API  │  │ SMTP     │             │
│  └──────────┘  └──────────┘  └──────────┘             │
└─────────────────────────────────────────────────────────┘
```

### 7.2 Data Flow

```
1. Image Selection
   └→ Random selection from Dropbox folder
   
2. Download & Link Generation
   ├→ Download to /tmp/
   └→ Generate temporary shareable link
   
3. AI Analysis
   ├→ Send link to Replicate BLIP-2
   ├→ Receive caption
   └→ Receive mood analysis
   
4. Caption Enhancement
   ├→ Combine caption + mood
   ├→ Send to OpenAI GPT
   └→ Receive enhanced caption
   
5. Caption Formatting
   └→ Append hashtags
   
6. Distribution (Parallel)
   ├→ Instagram: Post photo + caption
   ├→ Telegram: Resize + send photo + caption
   └→ Email: Attach photo + send caption
   
7. Archive Management
   └→ Move image to archive folder
```

### 7.3 File Structure

```
SocialMediaPythonPublisher/
│
├── py_rotator_daily.py      # Main application script
├── py_db_auth.py             # Dropbox authentication helper
├── requirements.txt          # Python dependencies
├── README.md                 # Project overview
├── LICENSE                   # MIT License
│
├── .env                      # Environment variables (not in git)
├── .gitignore                # Git ignore rules
│
├── configfiles/
│   ├── SocialMediaConfig.ini # Application config (not in git)
│   └── SociaMediaConfig.ini.example  # Config template
│
├── dotenv.example            # Environment template
│
└── instasession.json         # Instagram session cache (auto-generated)
```

### 7.4 Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Language | Python 3.7+ | Core application |
| Async | asyncio | Asynchronous operations |
| Cloud Storage | Dropbox API | Image storage & management |
| Image Analysis | Replicate (BLIP-2) | AI vision model |
| Text Generation | OpenAI GPT | Caption creation |
| Instagram | instagrapi | Unofficial Instagram API |
| Telegram | python-telegram-bot | Bot messaging |
| Email | smtplib | Gmail SMTP |
| Image Processing | Pillow (PIL) | Resizing & manipulation |
| Configuration | configparser | INI file parsing |
| Environment | python-dotenv | Secret management |

---

## 8. Troubleshooting

### 8.1 Common Issues

#### Issue: "No image files found in Dropbox"

**Symptoms:**
```
ERROR:root:No image files found in Dropbox. Exiting.
```

**Causes:**
- Incorrect `image_folder` path in configuration
- Empty Dropbox folder
- Authentication issues

**Solutions:**
1. Verify folder path is correct (case-sensitive):
   ```ini
   [Dropbox]
   image_folder = /YourFolder/Images  # Must match exactly
   ```

2. Check Dropbox via web interface to confirm folder exists and contains images

3. Re-authenticate Dropbox:
   ```bash
   python py_db_auth.py .env
   ```

4. Test Dropbox connection:
   ```python
   import dropbox
   dbx = dropbox.Dropbox(oauth2_refresh_token='...', app_key='...')
   result = dbx.files_list_folder('/YourFolder/Images')
   print([entry.name for entry in result.entries])
   ```

---

#### Issue: "Instagram login failed"

**Symptoms:**
```
ERROR:root:Failed to login with username and password
Exception: Instagram login failed.
```

**Causes:**
- Incorrect username/password
- Instagram security challenge
- Rate limiting
- Two-factor authentication enabled

**Solutions:**
1. Verify credentials in `.env`:
   ```bash
   INSTA_PASSWORD="your_correct_password"
   ```

2. Delete session file and retry:
   ```bash
   rm instasession.json
   python py_rotator_daily.py configfiles/SocialMediaConfig.ini
   ```

3. Disable two-factor authentication temporarily (Instagram account settings)

4. Login to Instagram manually from the same network first

5. Wait 1-2 hours if rate-limited

6. **Alternative:** Use official Instagram Graph API for production

---

#### Issue: "Telegram message failed"

**Symptoms:**
```
ERROR:root:Failed to send Telegram message: ...
```

**Causes:**
- Invalid bot token
- Incorrect chat/channel ID
- Bot not added to channel
- Network issues

**Solutions:**
1. Verify bot token format:
   ```bash
   TELEGRAM_BOT_TOKEN="123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
   ```

2. Check chat ID format:
   ```bash
   # For channels (must be admin):
   TELEGRAM_CHANNEL_ID="@your_channel"
   
   # For private chats (get from bot):
   TELEGRAM_CHANNEL_ID="-1001234567890"
   ```

3. Ensure bot is added to channel as administrator

4. Test bot independently:
   ```python
   import telegram
   import asyncio
   
   async def test():
       bot = telegram.Bot(token='your_token')
       await bot.send_message(chat_id='@channel', text='Test')
   
   asyncio.run(test())
   ```

---

#### Issue: "Email sending failed"

**Symptoms:**
```
ERROR:root:Failed to send email: ...
```

**Causes:**
- Email provider App Password not configured
- Incorrect SMTP settings (server or port)
- Firewall blocking SMTP ports
- Less secure app access disabled

**Solutions:**
1. **For Gmail** - Generate App Password:
   - Go to Google Account → Security
   - Enable 2-Step Verification
   - Generate App Password for "Mail"
   - Use generated password in `.env`

2. **Verify SMTP Configuration**:
   ```ini
   [Email]
   sender = your-email@provider.com
   recipient = recipient@example.com
   smtp_server = smtp.gmail.com      # Or your SMTP server
   smtp_port = 587                    # Or 465 for SSL
   ```
   
   Common SMTP settings:
   - Gmail: `smtp.gmail.com:587` (TLS) or `:465` (SSL)
   - Outlook/Office365: `smtp.office365.com:587`
   - Yahoo: `smtp.mail.yahoo.com:587`
   - Custom: Check your provider's documentation

3. **Test SMTP Connection**:
   ```python
   import smtplib
   
   # Use your configured settings
   smtp_server = 'smtp.gmail.com'  # From your config
   smtp_port = 587                  # From your config
   
   server = smtplib.SMTP(smtp_server, smtp_port)
   server.starttls()
   server.login('your-email@provider.com', 'app_password')
   print("Success!")
   server.quit()
   ```

4. **Check Firewall**: Ensure ports 587 (TLS) or 465 (SSL) are not blocked

5. **Try Alternative Port**: If port 587 doesn't work, try port 465:
   ```ini
   [Email]
   smtp_port = 465
   ```

---

#### Issue: "OpenAI API error"

**Symptoms:**
```
ERROR:root:An error occurred: ...
```

**Causes:**
- Invalid API key
- Insufficient credits
- Rate limiting
- Model not available

**Solutions:**
1. Verify API key:
   ```bash
   OPENAI_API_KEY="sk-..."  # Must start with sk-
   ```

2. Check account credits at [platform.openai.com/account/usage](https://platform.openai.com/account/usage)

3. Try different model:
   ```ini
   [openAI]
   engine = gpt-3.5-turbo  # Cheaper alternative to gpt-4
   ```

4. Test API key:
   ```bash
   curl https://api.openai.com/v1/models \
     -H "Authorization: Bearer $OPENAI_API_KEY"
   ```

---

#### Issue: "Replicate API error"

**Symptoms:**
```
Various errors during image analysis
```

**Causes:**
- Invalid API token
- Insufficient credits
- Image URL not accessible
- Model unavailable

**Solutions:**
1. Verify token format:
   ```bash
   REPLICATE_API_TOKEN="r8_..."  # Must start with r8_
   ```

2. Check credits at [replicate.com/account/billing](https://replicate.com/account/billing)

3. Ensure Dropbox link is accessible (test in browser)

4. Test different model:
   ```ini
   [Replicate]
   model = salesforce/blip:2e1dddc8621f72155f24cf2e0adbde548458d3cab9f00c0139eea840d0ac4746
   ```

---

#### Issue: "Configuration file not found"

**Symptoms:**
```
ERROR:root:Usage: python py_rotato_daily.py /path/to/<config_file>
```

**Causes:**
- Incorrect file path
- File not created
- Wrong working directory

**Solutions:**
1. Use absolute path:
   ```bash
   python py_rotator_daily.py /Users/esmit/Documents/GitHub/SocialMediaPythonPublisher/configfiles/SocialMediaConfig.ini
   ```

2. Check current directory:
   ```bash
   pwd
   ls configfiles/
   ```

3. Create config from example:
   ```bash
   cp configfiles/SociaMediaConfig.ini.example configfiles/SocialMediaConfig.ini
   ```

---

#### Issue: "Module not found"

**Symptoms:**
```
ModuleNotFoundError: No module named 'dropbox'
```

**Causes:**
- Dependencies not installed
- Wrong Python environment
- Virtual environment not activated

**Solutions:**
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Activate virtual environment:
   ```bash
   source venv/bin/activate  # Linux/macOS
   venv\Scripts\activate     # Windows
   ```

3. Verify installation:
   ```bash
   pip list | grep dropbox
   ```

---

### 8.2 Debug Mode Troubleshooting

Enable debug mode to see detailed output:

```ini
[Content]
debug = True
```

**Debug Output Includes:**
- Temporary Dropbox links
- Image analysis results
- Generated captions
- Platform-specific sending confirmations

**Example Debug Session:**
```bash
python py_rotator_daily.py configfiles/SocialMediaConfig.ini
```

**Expected Output:**
```
Temporary Dropbox Link: https://dl.dropboxusercontent.com/...
Image Summary: A beautiful landscape with mountains...
Message: Capturing nature's beauty... #photography
Sending Telegram: Capturing nature's beauty...
Sending Instagram: Capturing nature's beauty...
INFO:root:Logged in via saved session
Successfully posted: {'media_id': '...', ...}
```

---

### 8.3 Logging

The application uses Python's `logging` module. To capture logs to a file:

```bash
python py_rotator_daily.py configfiles/SocialMediaConfig.ini 2>&1 | tee socialmedia.log
```

**View logs:**
```bash
tail -f socialmedia.log
```

**Filter errors:**
```bash
grep ERROR socialmedia.log
```

---

### 8.4 Network Issues

#### Symptoms:
- Timeouts
- Connection errors
- Intermittent failures

#### Solutions:

1. **Test internet connection:**
   ```bash
   ping google.com
   ```

2. **Check API status pages:**
   - [Dropbox Status](https://status.dropbox.com/)
   - [OpenAI Status](https://status.openai.com/)
   - [Telegram Status](https://telegram.org/)

3. **Configure proxy (if needed):**
   ```bash
   export HTTP_PROXY=http://proxy.example.com:8080
   export HTTPS_PROXY=http://proxy.example.com:8080
   ```

4. **Increase timeouts** (requires code modification)

---

### 8.5 Permission Issues

#### Symptoms:
```
PermissionError: [Errno 13] Permission denied: '/tmp/image.jpg'
```

#### Solutions:

1. **Check tmp directory permissions:**
   ```bash
   ls -la /tmp/
   ```

2. **Fix permissions:**
   ```bash
   chmod 755 /tmp
   ```

3. **Use alternative temp directory** (code modification needed)

---

### 8.6 Rate Limiting

#### API Rate Limits:

| Service | Limit | Reset Period |
|---------|-------|--------------|
| Instagram | ~200 actions/hour | Rolling |
| OpenAI (GPT-3.5) | 3,500 RPM | Per minute |
| Replicate | 50 requests/minute | Per minute |
| Telegram | 30 messages/second | Per second |

#### Solutions:

1. **Reduce posting frequency**
2. **Add delays between API calls**
3. **Use higher-tier API plans**
4. **Implement exponential backoff**

---

## 9. Advanced Topics

### 9.1 Customizing AI Prompts

#### OpenAI System Prompt Customization

The `systemcontent` defines the AI's personality and expertise:

```ini
[openAI]
# Example 1: Photography Focus
systemcontent = You are an expert photographer and social media manager specializing in visual storytelling. You create compelling, authentic captions that highlight technical and emotional aspects of photography.

# Example 2: Business/Marketing Focus
systemcontent = You are a digital marketing expert specializing in engagement-driven content. You create captions that drive action, use power words, and incorporate call-to-actions.

# Example 3: Casual/Personal Focus
systemcontent = You are a friendly content creator who shares life's moments authentically. You write relatable, conversational captions that feel personal and genuine.
```

#### Role Content Customization

The `rolecontent` is the instruction prefix:

```ini
# Current default:
rolecontent = Write me a caption for a photograph that shows

# Alternative options:
rolecontent = Create an engaging Instagram caption for this image:
rolecontent = Write a short, witty caption (max 50 words) for:
rolecontent = Generate a professional photography caption describing:
```

#### Complete Caption Workflow

```
Replicate Output: "A sunset over mountains peaceful serene"
           ↓
OpenAI Prompt: "Write me a caption for a photograph that shows A sunset over mountains peaceful serene"
           ↓
OpenAI Output: "Golden hour magic at its finest. Nature's canvas never fails to amaze."
           ↓
Final Caption: "Golden hour magic at its finest. Nature's canvas never fails to amaze. #photography #sunset #nature"
```

---

### 9.2 Multiple Configuration Profiles

Create different configurations for different content types:

```bash
# Directory structure
configfiles/
  ├── landscape.ini    # Landscape photography config
  ├── portrait.ini     # Portrait photography config
  ├── product.ini      # Product photography config
  └── personal.ini     # Personal posts config
```

**landscape.ini:**
```ini
[Content]
hashtag_string = #landscape #nature #outdoors
instagram = True
telegram = True

[openAI]
systemcontent = You are a landscape photography expert...
```

**portrait.ini:**
```ini
[Content]
hashtag_string = #portrait #people #photography
instagram = True
telegram = False

[openAI]
systemcontent = You are a portrait photography expert...
```

**Usage:**
```bash
# Schedule different configs at different times
0 9 * * * python py_rotator_daily.py configfiles/landscape.ini
0 15 * * * python py_rotator_daily.py configfiles/portrait.ini
```

---

### 9.3 Extending Platform Support

#### Adding Twitter/X Support

```python
# In py_rotator_daily.py, add:

import tweepy

async def post_to_twitter(api_key, api_secret, access_token, access_secret, image_path, message):
    """Post image to Twitter/X"""
    try:
        auth = tweepy.OAuthHandler(api_key, api_secret)
        auth.set_access_token(access_token, access_secret)
        api = tweepy.API(auth)
        
        media = api.media_upload(image_path)
        api.update_status(status=message, media_ids=[media.media_id])
        
        logging.info("Posted to Twitter successfully")
    except Exception as e:
        logging.error(f"Twitter posting failed: {e}")
```

#### Configuration Changes:

```ini
[Content]
twitter = True

[Twitter]
api_key = your_key
api_secret = your_secret
access_token = your_token
access_secret = your_secret
```

---

### 9.4 Advanced Image Processing

#### Watermarking Images

```python
from PIL import Image, ImageDraw, ImageFont

def add_watermark(image_path, watermark_text):
    """Add watermark to image"""
    img = Image.open(image_path)
    draw = ImageDraw.Draw(img)
    
    # Use a watermark font
    font = ImageFont.truetype("arial.ttf", 36)
    
    # Position watermark at bottom right
    text_width, text_height = draw.textsize(watermark_text, font)
    position = (img.width - text_width - 10, img.height - text_height - 10)
    
    # Add semi-transparent watermark
    draw.text(position, watermark_text, font=font, fill=(255, 255, 255, 128))
    
    watermarked_path = image_path.replace('.jpg', '_watermarked.jpg')
    img.save(watermarked_path)
    return watermarked_path
```

#### Automatic Cropping for Platform Specs

```python
def crop_for_instagram(image_path):
    """Crop image to Instagram's 4:5 aspect ratio"""
    img = Image.open(image_path)
    width, height = img.size
    
    target_ratio = 4 / 5
    current_ratio = width / height
    
    if current_ratio > target_ratio:
        # Too wide, crop width
        new_width = int(height * target_ratio)
        left = (width - new_width) // 2
        img = img.crop((left, 0, left + new_width, height))
    else:
        # Too tall, crop height
        new_height = int(width / target_ratio)
        top = (height - new_height) // 2
        img = img.crop((0, top, width, top + new_height))
    
    cropped_path = image_path.replace('.jpg', '_cropped.jpg')
    img.save(cropped_path)
    return cropped_path
```

---

### 9.5 Analytics and Reporting

#### Track Posting Statistics

```python
import json
from datetime import datetime

def log_post_stats(image_name, platforms, caption):
    """Log posting statistics to JSON file"""
    stats = {
        'timestamp': datetime.now().isoformat(),
        'image': image_name,
        'platforms': platforms,
        'caption_length': len(caption),
        'hashtag_count': caption.count('#')
    }
    
    with open('post_stats.json', 'a') as f:
        json.dump(stats, f)
        f.write('\n')
```

#### Generate Monthly Reports

```bash
# Count posts per month
cat post_stats.json | grep "2024-10" | wc -l

# Average caption length
cat post_stats.json | jq '.caption_length' | awk '{sum+=$1} END {print sum/NR}'
```

---

### 9.6 Error Recovery and Retries

#### Implement Retry Logic

```python
import time
from functools import wraps

def retry(max_attempts=3, delay=5):
    """Decorator for retrying failed operations"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        raise
                    logging.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
                    time.sleep(delay)
        return wrapper
    return decorator

# Usage
@retry(max_attempts=3, delay=10)
async def post_image_to_instagram_with_retry(username, password, image_path, caption):
    return await post_image_to_instagram(username, password, image_path, caption)
```

---

### 9.7 Content Scheduling

#### Queue System

```python
import json
from datetime import datetime, timedelta

def add_to_queue(image_name, scheduled_time):
    """Add image to posting queue"""
    queue_item = {
        'image': image_name,
        'scheduled_time': scheduled_time.isoformat(),
        'status': 'pending'
    }
    
    with open('post_queue.json', 'a') as f:
        json.dump(queue_item, f)
        f.write('\n')

def process_queue():
    """Process scheduled posts"""
    with open('post_queue.json', 'r') as f:
        queue = [json.loads(line) for line in f]
    
    now = datetime.now()
    for item in queue:
        scheduled = datetime.fromisoformat(item['scheduled_time'])
        if now >= scheduled and item['status'] == 'pending':
            # Process this post
            process_scheduled_post(item['image'])
            item['status'] = 'completed'
    
    # Update queue file
    with open('post_queue.json', 'w') as f:
        for item in queue:
            json.dump(item, f)
            f.write('\n')
```

---

### 9.8 Database Integration

#### SQLite for Post History

```python
import sqlite3

def init_database():
    """Initialize post history database"""
    conn = sqlite3.connect('post_history.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_name TEXT,
            caption TEXT,
            platforms TEXT,
            posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            success BOOLEAN
        )
    ''')
    
    conn.commit()
    conn.close()

def log_post(image_name, caption, platforms, success):
    """Log post to database"""
    conn = sqlite3.connect('post_history.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO posts (image_name, caption, platforms, success)
        VALUES (?, ?, ?, ?)
    ''', (image_name, caption, ','.join(platforms), success))
    
    conn.commit()
    conn.close()

def get_post_history(days=30):
    """Retrieve post history"""
    conn = sqlite3.connect('post_history.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM posts
        WHERE posted_at >= datetime('now', '-' || ? || ' days')
        ORDER BY posted_at DESC
    ''', (days,))
    
    results = cursor.fetchall()
    conn.close()
    return results
```

---

### 9.9 Security Enhancements

#### Encrypt Sensitive Configuration

```python
from cryptography.fernet import Fernet

def generate_key():
    """Generate encryption key"""
    key = Fernet.generate_key()
    with open('secret.key', 'wb') as key_file:
        key_file.write(key)
    return key

def encrypt_env_file():
    """Encrypt .env file"""
    key = open('secret.key', 'rb').read()
    fernet = Fernet(key)
    
    with open('.env', 'rb') as file:
        original = file.read()
    
    encrypted = fernet.encrypt(original)
    
    with open('.env.encrypted', 'wb') as encrypted_file:
        encrypted_file.write(encrypted)

def decrypt_env_file():
    """Decrypt .env file"""
    key = open('secret.key', 'rb').read()
    fernet = Fernet(key)
    
    with open('.env.encrypted', 'rb') as encrypted_file:
        encrypted = encrypted_file.read()
    
    decrypted = fernet.decrypt(encrypted)
    return decrypted.decode()
```

---

### 9.10 Performance Optimization

#### Parallel Processing

```python
import asyncio

async def post_to_all_platforms_parallel(config, image_file, message):
    """Post to all platforms simultaneously"""
    tasks = []
    
    if config['run_telegram']:
        tasks.append(send_telegram_message(
            config['bot_token'],
            config['chat_id'],
            image_file,
            message
        ))
    
    if config['run_instagram']:
        tasks.append(post_image_to_instagram(
            config['instaname'],
            config['instaword'],
            image_file,
            message
        ))
    
    if config['run_fetlife']:
        tasks.append(send_email(image_file, message, config))
    
    # Execute all tasks concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Check results
    success = all(not isinstance(r, Exception) for r in results)
    return success
```

---

## Support and Contribution

### Getting Help

1. **Documentation**: Review this complete guide
2. **Troubleshooting**: Check [Section 8](#8-troubleshooting)
3. **GitHub Issues**: Search existing issues or create new one
4. **Community**: Join discussions on GitHub Discussions

### Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes with tests
4. Commit your changes (`git commit -m 'Add amazing feature'`)
5. Push to the branch (`git push origin feature/amazing-feature`)
6. Open a Pull Request

### Reporting Bugs

Include in your bug report:
- Python version
- Operating system
- Complete error message
- Configuration (sanitized)
- Steps to reproduce

### Feature Requests

Describe:
- Use case
- Expected behavior
- Potential implementation approach

---

## Appendix

### A. Environment Variable Reference

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `DROPBOX_APP_KEY` | Yes | Dropbox app key | `abc123...` |
| `DROPBOX_APP_PASSWORD` | Yes | Dropbox app secret | `xyz789...` |
| `DROPBOX_REFRESH_TOKEN` | Yes | OAuth refresh token | `sl.ABC...` |
| `OPENAI_API_KEY` | Yes | OpenAI API key | `sk-...` |
| `REPLICATE_API_TOKEN` | Yes | Replicate API token | `r8_...` |
| `TELEGRAM_BOT_TOKEN` | Conditional | Telegram bot token | `123:ABC...` |
| `TELEGRAM_CHANNEL_ID` | Conditional | Telegram chat/channel ID | `@channel` |
| `INSTA_PASSWORD` | Conditional | Instagram password | `password` |
| `EMAIL_PASSWORD` | Conditional | Gmail app password | `abcd efgh...` |

### B. Configuration File Reference

Complete INI file structure:

```ini
[Email]
sender = string          # Gmail address
recipient = string       # Recipient email

[Instagram]
name = string           # Username without @

[Dropbox]
image_folder = string   # Absolute path starting with /

[Content]
hashtag_string = string # Space-separated hashtags
telegram = boolean      # True or False
fetlife = boolean       # True or False
instagram = boolean     # True or False
archive = boolean       # True or False
debug = boolean         # True or False

[Replicate]
model = string          # Full model identifier

[openAI]
engine = string         # Model name
systemcontent = string  # System prompt
rolecontent = string    # Role prompt prefix
```

### C. API Cost Estimation

**Monthly costs for 30 posts (1 per day):**

| Service | Cost per Call | Monthly (30 posts) |
|---------|--------------|-------------------|
| OpenAI (GPT-3.5-Turbo) | ~$0.002 | ~$0.06 |
| Replicate (BLIP-2) | ~$0.05 | ~$1.50 |
| **Total** | | **~$1.56/month** |

**Notes:**
- Dropbox: Free tier sufficient (2GB)
- Telegram: Free
- Instagram: Free (no official API costs)
- Gmail: Free

### D. Glossary

- **Async/Await**: Python asynchronous programming pattern
- **BLIP-2**: Bootstrapped Language-Image Pre-training (AI vision model)
- **Caption**: Text description accompanying social media post
- **Cron**: Time-based job scheduler in Unix-like operating systems
- **Dropbox**: Cloud storage service
- **GPT**: Generative Pre-trained Transformer (OpenAI's language model)
- **Hashtag**: Metadata tag used on social media (e.g., #photography)
- **INI File**: Configuration file format with sections and key-value pairs
- **OAuth2**: Open standard for access delegation
- **Refresh Token**: Long-lived token for obtaining new access tokens
- **Replicate**: Platform for running AI models
- **Session**: Persistent authentication state
- **SMTP**: Simple Mail Transfer Protocol (email sending)

---

**Document Version**: 1.0  
**Last Updated**: October 31, 2025  
**Maintained By**: SocialMediaPythonPublisher Contributors  
**License**: MIT

---

*For the latest version of this documentation, visit the [GitHub repository](https://github.com/yourusername/SocialMediaPythonPublisher).*
