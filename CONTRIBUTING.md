# Contributing to Social Media Python Publisher

First off, thank you for considering contributing to Social Media Python Publisher! It's people like you that make this tool better for everyone.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [How Can I Contribute?](#how-can-i-contribute)
- [Development Setup](#development-setup)
- [Coding Standards](#coding-standards)
- [Pull Request Process](#pull-request-process)
- [Testing Guidelines](#testing-guidelines)
- [Documentation Standards](#documentation-standards)

---

## Code of Conduct

### Our Pledge

We pledge to make participation in our project a harassment-free experience for everyone, regardless of age, body size, disability, ethnicity, gender identity and expression, level of experience, nationality, personal appearance, race, religion, or sexual identity and orientation.

### Our Standards

**Positive behaviors include:**
- Using welcoming and inclusive language
- Being respectful of differing viewpoints and experiences
- Gracefully accepting constructive criticism
- Focusing on what is best for the community
- Showing empathy towards other community members

**Unacceptable behaviors include:**
- Trolling, insulting/derogatory comments, and personal attacks
- Public or private harassment
- Publishing others' private information without permission
- Other conduct which could reasonably be considered inappropriate

---

## Getting Started

### Prerequisites

Before contributing, make sure you have:
- Python 3.7 or higher installed
- Git installed and configured
- A GitHub account
- Familiarity with the project (read the [Documentation](DOCUMENTATION.md))

### Fork and Clone

1. Fork the repository on GitHub
2. Clone your fork locally:
```bash
git clone https://github.com/YOUR_USERNAME/SocialMediaPythonPublisher.git
cd SocialMediaPythonPublisher
```

3. Add the upstream repository:
```bash
git remote add upstream https://github.com/ORIGINAL_OWNER/SocialMediaPythonPublisher.git
```

---

## How Can I Contribute?

### Reporting Bugs

**Before submitting a bug report:**
- Check the [Documentation](DOCUMENTATION.md) and [Troubleshooting Guide](DOCUMENTATION.md#8-troubleshooting)
- Check existing [GitHub Issues](https://github.com/ORIGINAL_OWNER/SocialMediaPythonPublisher/issues)
- Ensure you're using the latest version

**When submitting a bug report, include:**
- Clear, descriptive title
- Exact steps to reproduce
- Expected behavior vs actual behavior
- Python version and OS
- Relevant configuration (sanitize sensitive data!)
- Error messages and logs
- Screenshots if applicable

**Bug Report Template:**
```markdown
**Describe the bug**
A clear description of what the bug is.

**To Reproduce**
Steps to reproduce:
1. Configure settings as '...'
2. Run command '...'
3. See error

**Expected behavior**
What you expected to happen.

**Environment:**
- OS: [e.g. macOS 12.0]
- Python version: [e.g. 3.9.7]
- Package versions: (output of `pip freeze`)

**Additional context**
Any other relevant information.
```

### Suggesting Enhancements

**Enhancement suggestions should include:**
- Clear, descriptive title
- Detailed description of the proposed feature
- Explanation of why this would be useful
- Possible implementation approach
- Examples or mockups if applicable

### Pull Requests

We actively welcome your pull requests!

---

## Development Setup

### 1. Install Dependencies

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install development dependencies
pip install -r requirements-dev.txt  # If available
```

### 2. Set Up Configuration

```bash
# Copy example files
cp dotenv.example .env
cp configfiles/SociaMediaConfig.ini.example configfiles/SocialMediaConfig.ini

# Edit with test credentials (never use production credentials!)
```

### 3. Create a Branch

```bash
# Update your fork
git fetch upstream
git checkout main
git merge upstream/main

# Create feature branch
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

### Branch Naming Convention

- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation changes
- `refactor/` - Code refactoring
- `test/` - Adding or updating tests
- `chore/` - Maintenance tasks

---

## Coding Standards

### Python Style Guide

We follow [PEP 8](https://pep8.org/) with some modifications:

**Key Points:**
- Maximum line length: 120 characters
- Use 4 spaces for indentation (no tabs)
- Use snake_case for functions and variables
- Use PascalCase for classes
- Use UPPER_CASE for constants

### Code Quality Tools

**Run before committing:**

```bash
# Format code
black py_db_auth.py py_rotator_daily.py

# Check style
flake8 py_db_auth.py py_rotator_daily.py

# Type checking
mypy py_db_auth.py py_rotator_daily.py

# Sort imports
isort py_db_auth.py py_rotator_daily.py
```

### Type Hints

All new code should include type hints:

```python
# Good
def process_image(image_path: str, quality: int = 85) -> bool:
    """Process an image file.
    
    Args:
        image_path: Path to the image file
        quality: JPEG quality (1-100)
        
    Returns:
        True if successful, False otherwise
    """
    # Implementation
    return True

# Bad
def process_image(image_path, quality=85):
    # Implementation
    return True
```

### Docstrings

Use Google-style docstrings:

```python
def send_to_platform(
    platform: str,
    image: str,
    caption: str,
    credentials: dict
) -> bool:
    """Send image and caption to a social media platform.
    
    This function handles authentication, image upload, and posting
    to the specified platform.
    
    Args:
        platform: Platform name (instagram, telegram, email)
        image: Path to the image file
        caption: Text caption for the post
        credentials: Dictionary containing platform credentials
        
    Returns:
        True if post was successful, False otherwise
        
    Raises:
        ValueError: If platform is not supported
        ConnectionError: If unable to connect to platform API
        
    Example:
        >>> credentials = {'token': 'abc123'}
        >>> send_to_platform('telegram', 'photo.jpg', 'Hello!', credentials)
        True
    """
    # Implementation
```

### Error Handling

**Do:**
- Catch specific exceptions
- Provide meaningful error messages
- Log errors appropriately
- Clean up resources in finally blocks

```python
# Good
try:
    result = api_call()
except requests.exceptions.Timeout as e:
    logging.error(f"API timeout: {e}")
    raise
except requests.exceptions.RequestException as e:
    logging.error(f"API request failed: {e}")
    raise
```

**Don't:**
- Use bare `except` clauses
- Silently ignore errors
- Use exceptions for flow control

```python
# Bad
try:
    result = api_call()
except:
    pass  # Silent failure!
```

### Constants and Configuration

```python
# Use constants for magic numbers
MAX_IMAGE_WIDTH = 1280
RESIZE_QUALITY = 85
API_TIMEOUT = 30

# Not hardcoded values
img.resize((1280, height))  # Bad
img.resize((MAX_IMAGE_WIDTH, height))  # Good
```

---

## Pull Request Process

### 1. Before Submitting

**Checklist:**
- [ ] Code follows the style guidelines
- [ ] All tests pass
- [ ] New code has tests
- [ ] Documentation is updated
- [ ] Commit messages are clear
- [ ] No merge conflicts
- [ ] No sensitive data in commits

### 2. Commit Messages

Follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>[optional scope]: <description>

[optional body]

[optional footer]
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

**Examples:**
```
feat(instagram): add video upload support

fix(auth): handle expired refresh tokens correctly

docs(readme): update installation instructions

refactor(main): split main() into smaller functions

test(image): add tests for image resizing
```

### 3. Create Pull Request

**PR Title:** Use the same format as commit messages

**PR Description Template:**
```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Related Issues
Fixes #123

## Testing
- [ ] All existing tests pass
- [ ] Added new tests
- [ ] Manually tested

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] No breaking changes (or documented)

## Screenshots (if applicable)
```

### 4. Review Process

1. **Automated checks** must pass (linting, tests)
2. **Code review** by at least one maintainer
3. **Requested changes** must be addressed
4. **Approval** from maintainer(s)
5. **Merge** by maintainer

**During review:**
- Be responsive to feedback
- Make requested changes promptly
- Keep discussion professional and constructive
- Update PR description if scope changes

---

## Testing Guidelines

### Test Structure

```python
# tests/test_image_manager.py
import pytest
from unittest.mock import Mock, patch
from py_rotator_daily import resize_image, list_images_in_dropbox

class TestImageManager:
    """Tests for image management functions."""
    
    def test_resize_image_maintains_aspect_ratio(self):
        """Test that resize maintains aspect ratio."""
        # Arrange
        original_image = "test_image.jpg"
        expected_width = 1280
        
        # Act
        result = resize_image(original_image)
        
        # Assert
        assert result is not None
        # Add more assertions
        
    @patch('dropbox.Dropbox')
    async def test_list_images_returns_only_images(self, mock_dbx):
        """Test that list_images filters non-image files."""
        # Arrange
        mock_dbx.files_list_folder.return_value = Mock(entries=[
            Mock(name='image.jpg'),
            Mock(name='document.pdf'),
            Mock(name='photo.png')
        ])
        
        # Act
        images = await list_images_in_dropbox(mock_dbx, '/test')
        
        # Assert
        assert 'document.pdf' not in images
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Run specific test file
pytest tests/test_image_manager.py

# Run specific test
pytest tests/test_image_manager.py::TestImageManager::test_resize_image
```

### Test Coverage

- Aim for **70%+ code coverage**
- All new features must have tests
- Bug fixes should include regression tests

---

## Documentation Standards

### Code Documentation

1. **Module docstrings** at the top of each file
2. **Function docstrings** for all public functions
3. **Inline comments** for complex logic
4. **Type hints** for all parameters and returns

### User Documentation

When adding features, update:
- `DOCUMENTATION.md` - Usage instructions
- `README.md` - If it affects quick start
- `DESIGN_SPECIFICATIONS.md` - If it changes architecture

### Examples

Provide examples for new features:
```python
# In docstring
Example:
    >>> config = read_config('config.ini')
    >>> print(config['image_folder'])
    '/Photos/Social'
```

---

## Development Workflow

### Typical Workflow

```bash
# 1. Sync with upstream
git fetch upstream
git checkout main
git merge upstream/main

# 2. Create feature branch
git checkout -b feature/my-feature

# 3. Make changes
# ... edit files ...

# 4. Test changes
pytest
flake8 .

# 5. Commit changes
git add .
git commit -m "feat: add new feature"

# 6. Push to your fork
git push origin feature/my-feature

# 7. Create Pull Request on GitHub
```

### Keeping Your Branch Updated

```bash
# While on your feature branch
git fetch upstream
git rebase upstream/main

# If there are conflicts, resolve them, then:
git rebase --continue
```

---

## Priority Areas for Contribution

See [REVIEW_SUMMARY.md](REVIEW_SUMMARY.md) for current priorities.

### High Priority
1. **Security improvements** - Encrypt session files, move SMTP config
2. **Test coverage** - Unit and integration tests
3. **Error handling** - Replace generic exception handling
4. **Code refactoring** - Split long functions

### Medium Priority
1. **Type annotations** - Complete type hints
2. **Documentation** - Function docstrings
3. **Platform adapters** - Abstract platform-specific code
4. **Configuration validation** - Input validation

### Good First Issues
Look for issues labeled `good-first-issue`:
- Documentation improvements
- Adding code comments
- Fixing typos
- Small bug fixes

---

## Getting Help

**Questions?**
- Read the [Documentation](DOCUMENTATION.md)
- Check [existing issues](https://github.com/ORIGINAL_OWNER/SocialMediaPythonPublisher/issues)
- Create a new issue with the `question` label

**Stuck?**
- Comment on your PR or issue
- Tag a maintainer with `@username`

---

## Recognition

Contributors will be:
- Listed in the project README
- Credited in release notes
- Recognized in the CONTRIBUTORS file

---

## License

By contributing, you agree that your contributions will be licensed under the same license as the project (MIT License).

---

**Thank you for contributing! 🎉**

Your efforts help make this project better for everyone in the community.

