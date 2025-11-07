# Changelog

All notable changes to the Social Media Python Publisher project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Comprehensive documentation in `docs/` folder
  - Complete user guide (DOCUMENTATION.md)
  - Detailed code review report (CODE_REVIEW_REPORT.md)
  - Design specifications (DESIGN_SPECIFICATIONS.md)
  - Quick reference summary (REVIEW_SUMMARY.md)
  - SMTP update documentation (SMTP_UPDATE_SUMMARY.md)
  - Setup guide moved to `docs/reports/` (SETUP_COMPLETE.md)
- GitHub integration
  - Security scan workflow (automated weekly scans)
  - Code quality workflow (automated checks)
  - Bug report template
  - Feature request template
  - Pull request template
- Development tools
  - Makefile with 15+ commands
  - Pre-commit hooks configuration
  - EditorConfig for consistent formatting
  - requirements-dev.txt for development dependencies
- Security enhancements
  - Enhanced .gitignore with 40+ security patterns
  - .cursorignore to protect sensitive data from AI indexing
  - SECURITY.md with security policy
  - Automated secret scanning
- Configurable SMTP settings in Email configuration
  - `smtp_server` option to support any SMTP provider
  - `smtp_port` option to customize port (587, 465, 25)
  - Backward compatible with default Gmail settings
- CHANGELOG.md in project root for version tracking

### Changed
- **BREAKING**: Moved all documentation to `docs/` folder
- **IMPORTANT**: Email SMTP server is now configurable via INI file
  - Previously hardcoded to `smtp.gmail.com:587`
  - Now supports Gmail, Outlook, Yahoo, and custom SMTP servers
  - Defaults to Gmail if not specified (backward compatible)
- Updated example configuration file with better comments
- Improved configuration file formatting and clarity
- Updated README with new documentation structure
- Organized reports into `docs/reports/` subdirectory
- Updated CODE_REVIEW_REPORT.md to reflect recent improvements
  - Overall rating improved from B- (6.0/10) to B+ (7.1/10)
  - Documented all resolved issues
  - Added "Recent Improvements" section

### Fixed
- Hardcoded SMTP server issue - now configurable via config file
- Configuration file example had inconsistent formatting
- Missing default values for optional Email configuration
- Documentation organization improved for better navigation

### Security
- Added 4 layers of credential protection
- Implemented automated security scanning
- Added secret detection in pre-commit hooks
- Enhanced gitignore to prevent credential leaks

## [1.0.0] - 2025-10-31

### Added
- Initial release
- Multi-platform social media posting (Instagram, Telegram, Email)
- AI-powered caption generation using OpenAI GPT
- Image analysis using Replicate BLIP-2
- Dropbox integration for image storage and archiving
- Configuration via INI files and environment variables
- Session management for Instagram authentication
- Debug mode for testing without archiving
- Async/await operations for I/O efficiency

### Features
- Random image selection from Dropbox
- Automatic AI-generated captions
- Multi-platform distribution
- Automatic image archiving
- Configurable hashtags
- Image resizing for Telegram

---

## Migration Guide

### Upgrading to Configurable SMTP

If you're upgrading from a version before the SMTP configuration change:

#### What Changed
The email SMTP server and port were previously hardcoded to Gmail (`smtp.gmail.com:587`). They are now configurable in your INI file.

#### Action Required (Optional)
Your existing configuration will continue to work with Gmail. However, to use other email providers or customize settings, add these lines to your config:

```ini
[Email]
sender = your-email@provider.com
recipient = recipient@example.com
smtp_server = smtp.gmail.com     # Add this line
smtp_port = 587                   # Add this line
```

#### For Other Providers

**Outlook/Office365:**
```ini
smtp_server = smtp.office365.com
smtp_port = 587
```

**Yahoo Mail:**
```ini
smtp_server = smtp.mail.yahoo.com
smtp_port = 587
```

**Custom SMTP:**
```ini
smtp_server = mail.yourdomain.com
smtp_port = 587  # Or 465 for SSL
```

#### Backward Compatibility
If you don't add these settings, the application will default to Gmail settings, maintaining backward compatibility with existing configurations.

---

## Notes

- Version numbers follow [Semantic Versioning](https://semver.org/)
- Keep this file updated with each release
- Document breaking changes clearly
- Include migration guides for major changes

