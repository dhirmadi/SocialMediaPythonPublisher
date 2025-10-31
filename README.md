# Social Media Python Publisher

[![Python Version](https://img.shields.io/badge/python-3.7%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-active-success.svg)]()

An intelligent automation system for social media content distribution across multiple platforms, powered by AI for smart caption generation.

---

## 📚 Documentation

**Complete documentation is now available!** Please refer to:

- **[📋 Review Summary](docs/REVIEW_SUMMARY.md)** - Quick overview and action items
- **[📖 Complete Documentation](docs/DOCUMENTATION.md)** - Full user guide, API reference, and troubleshooting
- **[🔍 Code Review Report](docs/CODE_REVIEW_REPORT.md)** - Detailed code analysis and recommendations
- **[🏗️ Design Specifications](docs/DESIGN_SPECIFICATIONS.md)** - Architecture and technical design

---

## 🚀 Quick Start

### Prerequisites
- Python 3.7 or higher
- API accounts for: Dropbox, OpenAI, Replicate, Telegram (optional), Instagram (optional)

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/yourusername/SocialMediaPythonPublisher.git
cd SocialMediaPythonPublisher
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Configure environment variables**
```bash
cp dotenv.example .env
# Edit .env with your API credentials
```

4. **Configure application settings**
```bash
cp configfiles/SociaMediaConfig.ini.example configfiles/SocialMediaConfig.ini
# Edit SocialMediaConfig.ini with your settings
```

5. **Authenticate with Dropbox**
```bash
python py_db_auth.py .env
```

6. **Run the application**
```bash
python py_rotator_daily.py configfiles/SocialMediaConfig.ini
```

For detailed setup instructions, see the [Complete Documentation](docs/DOCUMENTATION.md).

---

## ✨ Key Features

- **🤖 AI-Driven Caption Generation**: Leverages OpenAI GPT and Replicate BLIP-2 to generate engaging, context-aware captions
- **☁️ Cloud Storage Integration**: Seamless Dropbox integration for image management and archiving
- **📱 Multi-Platform Distribution**: Post simultaneously to Instagram, Telegram, and Email
- **⚙️ Flexible Configuration**: Customize behavior via environment variables and INI files
- **🔄 Automated Workflow**: Select → Analyze → Generate → Post → Archive
- **🐛 Debug Mode**: Test without archiving images
- **💾 Session Persistence**: Instagram login session caching for reliability

---

## 🎯 Use Cases

- **Content Creators**: Automate daily posting schedules
- **Photographers**: Share portfolio pieces across platforms
- **Small Businesses**: Maintain consistent social media presence
- **Digital Marketers**: Streamline content distribution workflows

---

## 📊 System Architecture

```
Image Selection (Dropbox)
         ↓
AI Analysis (Replicate)
         ↓
Caption Generation (OpenAI)
         ↓
Multi-Platform Distribution
    ├─ Instagram
    ├─ Telegram
    └─ Email
         ↓
Archiving (Dropbox)
```

For detailed architecture information, see [Design Specifications](docs/DESIGN_SPECIFICATIONS.md).

---

## 🔧 Configuration

### Environment Variables (.env)
```bash
DROPBOX_APP_KEY="your_key"
DROPBOX_APP_PASSWORD="your_secret"
DROPBOX_REFRESH_TOKEN="auto_generated"
OPENAI_API_KEY="sk-your_key"
REPLICATE_API_TOKEN="r8_your_token"
TELEGRAM_BOT_TOKEN="your_token"
TELEGRAM_CHANNEL_ID="@your_channel"
INSTA_PASSWORD="your_password"
EMAIL_PASSWORD="your_gmail_app_password"
```

### Application Settings (INI)
```ini
[Email]
sender = your-email@gmail.com
recipient = recipient@example.com
smtp_server = smtp.gmail.com
smtp_port = 587

[Content]
hashtag_string = #photography #art
archive = True
telegram = True
instagram = True
fetlife = False
debug = False
```

See [Documentation](docs/DOCUMENTATION.md#4-configuration) for complete configuration reference.

---

## 📋 Requirements

### Core Dependencies
- `dropbox` >= 11.0.0 - Cloud storage integration
- `openai` >= 1.7.2 - AI caption generation
- `replicate` >= 0.22.0 - Image analysis
- `instagrapi` >= 2.0.0 - Instagram posting
- `python-telegram-bot` >= 13.0 - Telegram integration
- `Pillow` >= 8.0.0 - Image processing

See [requirements.txt](requirements.txt) for complete list.

---

## 💡 Usage Examples

### Basic Usage
```bash
python py_rotator_daily.py configfiles/SocialMediaConfig.ini
```

### Debug Mode (No Archiving)
Edit your config file:
```ini
[Content]
debug = True
```

### Scheduled Execution (Cron)
```bash
0 9 * * * cd /path/to/project && python py_rotator_daily.py configfiles/SocialMediaConfig.ini
```

---

## 🐛 Troubleshooting

### Common Issues

**"No image files found in Dropbox"**
- Check `image_folder` path in configuration
- Verify Dropbox folder contains images
- Ensure proper authentication

**"Instagram login failed"**
- Verify credentials in `.env`
- Delete `instasession.json` and retry
- May need to login manually first

For complete troubleshooting guide, see [Documentation - Troubleshooting](docs/DOCUMENTATION.md#8-troubleshooting).

---

## 📈 Current Status & Improvements

### ✅ Working Well
- Multi-platform integration
- AI-powered caption generation
- Async/await operations
- Session management

### ⚠️ Areas for Improvement
- Security enhancements needed
- Add comprehensive testing
- Refactor long functions
- Improve error handling

See [Code Review Report](docs/CODE_REVIEW_REPORT.md) for detailed analysis and [Review Summary](docs/REVIEW_SUMMARY.md) for prioritized action items.

---

## 🗺️ Roadmap

### Phase 1: Critical Fixes (In Progress)
- [ ] Security improvements
- [ ] Enhanced error handling
- [ ] Configuration validation
- [ ] Temporary file cleanup

### Phase 2: Code Quality
- [ ] Comprehensive testing
- [ ] Code refactoring
- [ ] Complete type annotations
- [ ] Documentation improvements

### Phase 3: Feature Enhancements
- [ ] Additional platform support (TikTok, Twitter)
- [ ] Video content support
- [ ] Analytics dashboard
- [ ] Content scheduling

See [Design Specifications - Future Enhancements](docs/DESIGN_SPECIFICATIONS.md#10-future-enhancements) for details.

---

## 🤝 Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes with tests
4. Submit a pull request

See [Documentation - Contributing](docs/DOCUMENTATION.md#support-and-contribution) for guidelines.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🔗 Resources

- **[Complete Documentation](docs/DOCUMENTATION.md)** - Full guide with API reference
- **[Code Review Report](docs/CODE_REVIEW_REPORT.md)** - Detailed analysis
- **[Design Specifications](docs/DESIGN_SPECIFICATIONS.md)** - Technical architecture
- **[Review Summary](docs/REVIEW_SUMMARY.md)** - Quick reference guide
- **[Changelog](CHANGELOG.md)** - Version history and updates
- **[Setup Guide](docs/reports/SETUP_COMPLETE.md)** - Complete setup walkthrough

### External APIs
- [Dropbox API](https://www.dropbox.com/developers/documentation)
- [OpenAI API](https://platform.openai.com/docs)
- [Replicate](https://replicate.com/docs)
- [Telegram Bot API](https://core.telegram.org/bots)

---

## 💰 Operating Costs

Estimated monthly costs for 30 posts:
- OpenAI (GPT-3.5): ~$0.50-1.00
- Replicate (BLIP-2): ~$1.00-2.00
- Total: **~$1.50-3.00/month**

---

## ⚖️ Disclaimer

**Instagram Integration**: This tool uses an unofficial Instagram API (instagrapi) which may violate Instagram's Terms of Service. For production use, consider using the official Instagram Graph API.

---

## 📧 Support

For issues and questions:
1. Check the [Documentation](docs/DOCUMENTATION.md)
2. Review the [Troubleshooting Guide](docs/DOCUMENTATION.md#8-troubleshooting)
3. Check existing GitHub issues
4. Create a new issue with detailed information

---

**Made with ❤️ for content creators and social media managers**