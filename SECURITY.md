# Security Policy

## Supported Versions

We release security updates for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| 1.x.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Security Considerations

### Known Security Concerns

1. **Instagram API**: This application uses an unofficial Instagram API (instagrapi) which:
   - May violate Instagram's Terms of Service
   - Could result in account suspension
   - Is not officially supported
   - **Recommendation**: Use at your own risk or migrate to official Instagram Graph API

2. **Credential Storage**: 
   - Application stores credentials in `.env` file
   - Session tokens stored in `instasession.json`
   - **Recommendation**: Implement keyring-based credential storage (see documentation)

3. **Temporary Files**:
   - Images downloaded to `/tmp/` directory
   - May persist between runs
   - **Recommendation**: Ensure proper cleanup implementation

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability, please follow these steps:

### 1. Do NOT Disclose Publicly

Please **do not** create a public GitHub issue for security vulnerabilities.

### 2. Report Privately

Use one of these methods to report security issues:

- **Preferred**: Use GitHub's [Security Advisories](https://github.com/yourusername/SocialMediaPythonPublisher/security/advisories/new)
- **Alternative**: Email security concerns to your-email@example.com
- **Subject**: `[SECURITY] Brief description of issue`

### 3. Information to Include

Please provide:

- **Description** of the vulnerability
- **Steps to reproduce** the issue
- **Potential impact** of the vulnerability
- **Suggested fix** (if you have one)
- **Your contact information** for follow-up

### 4. Response Timeline

- **Initial Response**: Within 48 hours
- **Assessment**: Within 7 days
- **Fix Development**: Depends on severity (see below)
- **Public Disclosure**: After fix is released (coordinated disclosure)

### Severity Levels

| Severity | Response Time | Example |
|----------|--------------|---------|
| **Critical** | 24-48 hours | Remote code execution, credential theft |
| **High** | 3-7 days | Authentication bypass, data exposure |
| **Medium** | 14-30 days | XSS, CSRF, information disclosure |
| **Low** | 30-90 days | Minor information leaks, configuration issues |

## Security Best Practices

### For Users

1. **Protect Your Credentials**
   ```bash
   # Never commit these files
   .env
   *.ini (except .example files)
   *session.json
   ```

2. **Use Environment Variables**
   ```bash
   # Store secrets in .env, not in code
   export OPENAI_API_KEY="your-key-here"
   ```

3. **Review Permissions**
   ```bash
   # Set restrictive file permissions
   chmod 600 .env
   chmod 600 configfiles/*.ini
   chmod 600 instasession.json
   ```

4. **Regular Updates**
   ```bash
   # Keep dependencies updated
   pip install --upgrade -r requirements.txt
   ```

5. **Security Scanning**
   ```bash
   # Run security checks
   pip install safety bandit
   safety check
   bandit -r . -f json -o bandit-report.json
   ```

### For Contributors

1. **Never Commit Secrets**
   - Always review changes before committing
   - Use `.gitignore` properly
   - Scan for secrets: `git secrets --scan`

2. **Validate Input**
   ```python
   # Always validate user input
   if not validate_config(config):
       raise ValueError("Invalid configuration")
   ```

3. **Use Prepared Statements**
   ```python
   # When adding database support
   cursor.execute("SELECT * FROM posts WHERE id = ?", (post_id,))
   ```

4. **Sanitize Logs**
   ```python
   # Never log sensitive data
   logger.info(f"Posted to {platform}")  # Good
   logger.info(f"Using token {token}")   # BAD!
   ```

5. **Secure Defaults**
   ```python
   # Use secure defaults
   DEBUG = False  # Default to production mode
   VERIFY_SSL = True  # Always verify SSL
   ```

## Security Checklist for Deployment

Before deploying to production:

- [ ] All secrets stored in environment variables or secure vault
- [ ] `.env` file has permissions 600 (read/write owner only)
- [ ] Session files encrypted or in secure location
- [ ] Debug mode disabled
- [ ] Logging configured without sensitive data
- [ ] Dependencies updated and scanned for vulnerabilities
- [ ] Rate limiting implemented
- [ ] Error messages don't expose system information
- [ ] Temporary files cleaned up automatically
- [ ] HTTPS used for all API communications
- [ ] Authentication tokens regularly rotated

## Vulnerability Disclosure Policy

### Responsible Disclosure

We follow responsible disclosure:

1. **Private Notification**: Reporter notifies maintainers privately
2. **Assessment**: We assess and confirm the vulnerability
3. **Fix Development**: We develop and test a fix
4. **Coordinated Release**: We release the fix and notify users
5. **Public Disclosure**: After users have had time to update (typically 90 days)

### Recognition

Security researchers who responsibly disclose vulnerabilities will be:
- Thanked in release notes (if desired)
- Listed in our Security Hall of Fame
- Eligible for a bug bounty (if program exists)

## Security Updates

### Receiving Updates

To receive security updates:
1. **Watch the repository** on GitHub (select "Security alerts only")
2. Subscribe to release notifications
3. Follow the project on social media

### Applying Updates

```bash
# Pull latest changes
git pull origin main

# Update dependencies
pip install --upgrade -r requirements.txt

# Review CHANGELOG for security fixes
```

## Additional Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Python Security Best Practices](https://python.readthedocs.io/en/stable/library/security_warnings.html)
- [API Security Best Practices](https://owasp.org/www-project-api-security/)

## Contact

For security concerns, contact:
- **Security Email**: your-email@example.com
- **GitHub Security**: Use private security advisories
- **Response Time**: Within 48 hours

---

**Last Updated**: October 31, 2025  
**Version**: 1.0

Thank you for helping keep Social Media Python Publisher secure! 🔒

