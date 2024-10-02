# Social Media Automation Script

This repository contains a Python script designed for automating social media content distribution across various platforms. The script integrates with several APIs, including **Dropbox**, **OpenAI**, **Replicate**, **Telegram**, **Email**, and **Instagram** to streamline the management and posting of images with AI-generated captions. 

### Key Features:
- **AI-Driven Caption Generation**: Leverages OpenAI and Replicate to generate mood-based captions for images, enhancing content relevance and engagement.
- **Image Management**: Downloads, resizes, and archives images from Dropbox, allowing for automated content handling.
- **Multi-Platform Posting**: Distributes images with generated captions to Instagram, Telegram, and via email.
- **Customizable Configurations**: Reads configurations from environment variables and an INI file, allowing flexible integration with different accounts and settings.
- **Error Handling and Debugging**: Includes logging and debugging options for enhanced error tracking and troubleshooting.

### Requirements:
- Python 3.7+
- API tokens for OpenAI, Replicate, Dropbox, Instagram, and Telegram
- Environment variables setup for secure API interactions

### Usage:
Run the script by providing the path to your configuration file:
```bash
python script_name.py <config_file>
```

### Features in Detail:
- **Image Handling**: Automatically selects images from a Dropbox folder, resizes them, and generates temporary links.
- **AI Integration**: Queries OpenAI and Replicate to generate captions and mood descriptions for each image.
- **Cross-Platform Content Distribution**: Posts to Instagram, Telegram, and sends via email.
- **Archiving**: Moves images to an archive folder after successful distribution.

This script is designed to simplify social media management by automating repetitive tasks, allowing content creators to focus on engagement and creativity.