# Development Guide

This guide is for developers who want to contribute to or modify the Social Media Python Publisher.

## Table of Contents

1. [Setup Development Environment](#setup-development-environment)
2. [Project Structure](#project-structure)
3. [Development Workflow](#development-workflow)
4. [Testing](#testing)
5. [Code Quality](#code-quality)
6. [Security Guidelines](#security-guidelines)
7. [Git Workflow](#git-workflow)

---

## Setup Development Environment

### Prerequisites

- Python 3.9 or higher
- Git
- Virtual environment tool (venv, virtualenv, or conda)

### Initial Setup

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/SocialMediaPythonPublisher.git
cd SocialMediaPythonPublisher

# 2. Create virtual environment
python -m venv venv

# 3. Activate virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate

# 4. Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 5. Set up pre-commit hooks
pre-commit install

# 6. Copy example configuration files
cp dotenv.example .env
cp configfiles/SociaMediaConfig.ini.example configfiles/SocialMediaConfig.ini

# 7. Edit .env with your development credentials
# NEVER commit this file!
nano .env
```

### IDE Setup (Cursor/VS Code)

#### Cursor Settings

Create `.vscode/settings.json` (if not exists):

```json
{
  "python.linting.enabled": true,
  "python.linting.pylintEnabled": true,
  "python.linting.flake8Enabled": true,
  "python.formatting.provider": "black",
  "python.formatting.blackArgs": ["--line-length", "120"],
  "editor.formatOnSave": true,
  "python.testing.pytestEnabled": true,
  "python.testing.unittestEnabled": false,
  "files.exclude": {
    "**/__pycache__": true,
    "**/*.pyc": true,
    "**/.pytest_cache": true,
    "**/venv": true,
    "**/.env": true,
    "**/*.ini": true,
    "!**/*.ini.example": true
  }
}
```

---

## Project Structure

```
SocialMediaPythonPublisher/
├── .github/                    # GitHub configuration
│   ├── workflows/              # CI/CD pipelines
│   ├── ISSUE_TEMPLATE/         # Issue templates
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── DEVELOPMENT.md          # This file
│
├── docs/                       # Documentation
│   ├── DOCUMENTATION.md
│   ├── CODE_REVIEW_REPORT.md
│   ├── DESIGN_SPECIFICATIONS.md
│   └── REVIEW_SUMMARY.md
│
├── configfiles/                # Configuration examples
│   └── SociaMediaConfig.ini.example
│
├── tests/                      # Test suite (to be created)
│   ├── __init__.py
│   ├── test_config.py
│   ├── test_workflow.py
│   └── fixtures/
│
├── py_db_auth.py              # Dropbox authentication
├── py_rotator_daily.py        # Main application
├── requirements.txt            # Production dependencies
├── requirements-dev.txt        # Development dependencies
├── .gitignore                  # Git ignore rules
├── .cursorignore              # Cursor ignore rules
├── .editorconfig              # Editor configuration
├── .pre-commit-config.yaml    # Pre-commit hooks
└── README.md                   # Project overview
```

---

## Development Workflow

### 1. Create a Feature Branch

```bash
# Update main branch
git checkout main
git pull origin main

# Create feature branch
git checkout -b feature/your-feature-name
```

### 2. Make Changes

- Follow code style guidelines
- Add tests for new functionality
- Update documentation as needed
- Commit frequently with clear messages

### 3. Run Quality Checks

```bash
# Format code
black .
isort .

# Lint code
flake8 .
pylint py_rotator_daily.py py_db_auth.py

# Type checking
mypy .

# Run tests
pytest -v

# Run pre-commit hooks
pre-commit run --all-files
```

### 4. Commit Changes

```bash
# Stage changes
git add .

# Commit with descriptive message
git commit -m "feat: add support for Twitter platform"

# Pre-commit hooks will run automatically
```

### 5. Push and Create PR

```bash
# Push to GitHub
git push origin feature/your-feature-name

# Create Pull Request on GitHub
```

---

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Run specific test file
pytest tests/test_config.py

# Run with verbose output
pytest -v -s

# Run tests matching pattern
pytest -k "test_config"
```

### Writing Tests

```python
# tests/test_example.py
import pytest
from py_rotator_daily import read_config

def test_read_config_valid():
    """Test reading valid configuration"""
    config = read_config('tests/fixtures/valid_config.ini')
    assert config['image_folder'] == '/test/images'
    assert config['run_archive'] is True

@pytest.mark.asyncio
async def test_async_function():
    """Test async functions"""
    result = await some_async_function()
    assert result is not None
```

### Test Coverage Goals

- Overall: 80%+
- Critical paths: 90%+
- New features: 100%

---

## Code Quality

### Code Style

We follow PEP 8 with some modifications:

- **Line length**: 120 characters
- **Imports**: Sorted with isort (black profile)
- **Formatting**: black formatter
- **Docstrings**: Google style

### Example

```python
from typing import Dict, Optional

def read_config(configfile: str) -> Dict[str, any]:
    """
    Read and parse configuration from INI file.

    Args:
        configfile: Path to INI configuration file.

    Returns:
        Dictionary containing all configuration values.

    Raises:
        FileNotFoundError: If configfile doesn't exist.
        ValueError: If configuration is invalid.

    Example:
        >>> config = read_config('config.ini')
        >>> print(config['image_folder'])
        '/Images/ToPost'
    """
    # Implementation
    pass
```

### Type Hints

Always use type hints:

```python
# Good
def process_image(path: str, resize: bool = True) -> Optional[str]:
    pass

# Bad
def process_image(path, resize=True):
    pass
```

---

## Security Guidelines

### Never Commit Sensitive Data

**NEVER commit:**
- `.env` files
- `*.ini` configuration files (except `.example`)
- `*session.json` files
- API keys, tokens, passwords
- Personal data

### Pre-Commit Checks

Our pre-commit hooks will catch:
- Private keys
- API keys in code
- Common secrets patterns

### Code Security

```python
# Good - credentials from environment
api_key = os.getenv('OPENAI_API_KEY')

# Bad - hardcoded credentials
api_key = 'sk-abc123...'  # NEVER DO THIS!

# Good - sanitized logging
logger.info(f"Posted to {platform}")

# Bad - logging sensitive data
logger.info(f"Using token {api_key}")  # NEVER DO THIS!
```

### Security Scanning

```bash
# Check dependencies
safety check

# Scan code for security issues
bandit -r . -f json

# Detect secrets
detect-secrets scan
```

---

## Git Workflow

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks
- `security`: Security fixes

**Examples:**

```bash
feat(instagram): add support for Instagram Stories

- Implemented story upload functionality
- Added story-specific configuration options
- Updated documentation

Closes #42

---

fix(config): validate API keys at startup

Previously, invalid API keys would cause runtime errors.
Now they're validated during configuration loading.

---

security: sanitize error messages to prevent token exposure

BREAKING CHANGE: Error message format has changed
```

### Branch Naming

```
feature/feature-name
fix/bug-description
docs/documentation-update
refactor/component-name
security/vulnerability-fix
```

### Pull Request Process

1. **Create PR** with descriptive title
2. **Fill out template** completely
3. **Link related issues**
4. **Ensure CI passes**
5. **Request review**
6. **Address feedback**
7. **Squash and merge** when approved

---

## Development Tools

### Useful Commands

```bash
# Format code
make format  # or: black . && isort .

# Run linters
make lint    # or: flake8 . && pylint *.py

# Run tests
make test    # or: pytest

# Run all checks
make check   # or: pre-commit run --all-files

# Clean build artifacts
make clean   # or: rm -rf __pycache__ .pytest_cache
```

### Creating a Makefile

```makefile
# Makefile
.PHONY: help format lint test check clean

help:
	@echo "Available commands:"
	@echo "  make format  - Format code with black and isort"
	@echo "  make lint    - Run linters"
	@echo "  make test    - Run tests"
	@echo "  make check   - Run all quality checks"
	@echo "  make clean   - Clean build artifacts"

format:
	black .
	isort .

lint:
	flake8 .
	pylint py_rotator_daily.py py_db_auth.py
	mypy .

test:
	pytest -v --cov=.

check:
	pre-commit run --all-files

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete
	rm -rf htmlcov/ .coverage
```

---

## Debugging

### Local Development

```python
# Add debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Use debug mode in config
[Content]
debug = True
```

### Interactive Debugging

```python
# Insert breakpoint
import ipdb; ipdb.set_trace()

# Or use built-in breakpoint()
breakpoint()
```

### Common Issues

1. **Import errors**: Check virtual environment is activated
2. **API errors**: Verify credentials in `.env`
3. **Test failures**: Check test fixtures and mocks
4. **Pre-commit fails**: Run `pre-commit run --all-files` to see details

---

## Resources

- [Project Documentation](../docs/DOCUMENTATION.md)
- [Code Review Report](../docs/CODE_REVIEW_REPORT.md)
- [Design Specifications](../docs/DESIGN_SPECIFICATIONS.md)
- [Security Policy](../SECURITY.md)
- [Contributing Guidelines](../CONTRIBUTING.md)

---

## Getting Help

- **Documentation**: Check docs/ folder
- **Issues**: Search existing GitHub issues
- **Discussions**: Ask in GitHub Discussions
- **Discord/Slack**: [Link if exists]

---

**Happy Coding! 🚀**

