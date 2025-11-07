# Makefile for Social Media Python Publisher
# Simplifies common development tasks

.PHONY: help install install-dev format lint type-check test security clean setup-dev

# Default target
help:
	@echo "Social Media Python Publisher - Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install         Install production dependencies"
	@echo "  make install-dev     Install development dependencies"
	@echo "  make setup-dev       Complete development environment setup"
	@echo ""
	@echo "Code Quality:"
	@echo "  make format          Format code with black and isort"
	@echo "  make lint            Run linters (flake8, pylint)"
	@echo "  make type-check      Run type checker (mypy)"
	@echo "  make test            Run tests with coverage"
	@echo "  make check           Run all quality checks"
	@echo ""
	@echo "Security:"
	@echo "  make security        Run security scans"
	@echo "  make check-secrets   Check for exposed secrets"
	@echo ""
	@echo "Maintenance:"
	@echo "  make clean           Remove temporary files and caches"
	@echo "  make clean-all       Deep clean including venv"
	@echo ""
	@echo "Run Application:"
	@echo "  make run             Run application with default config"
	@echo "  make auth            Run Dropbox authentication"

# Installation
install:
	pip install -r requirements.txt

install-dev:
	pip install -r requirements.txt
	pip install -r requirements-dev.txt

setup-dev: install-dev
	@echo "Setting up pre-commit hooks..."
	pre-commit install
	@echo "Creating configuration files from examples..."
	@if [ ! -f .env ]; then cp dotenv.example .env; echo "Created .env - EDIT THIS FILE"; fi
	@if [ ! -f configfiles/SocialMediaConfig.ini ]; then \
		cp configfiles/SociaMediaConfig.ini.example configfiles/SocialMediaConfig.ini; \
		echo "Created SocialMediaConfig.ini - EDIT THIS FILE"; \
	fi
	@echo ""
	@echo "✅ Development environment setup complete!"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Edit .env with your API credentials"
	@echo "  2. Edit configfiles/SocialMediaConfig.ini with your settings"
	@echo "  3. Run 'make auth' to authenticate with Dropbox"
	@echo "  4. Run 'make test' to verify installation"

# Code Quality
format:
	@echo "Formatting code with black..."
	black . --line-length 120
	@echo "Sorting imports with isort..."
	isort . --profile black --line-length 120
	@echo "✅ Code formatted"

lint:
	@echo "Running flake8..."
	flake8 . --max-line-length=120 --extend-ignore=E203,E501 --exclude=venv,env,.venv,.git,__pycache__
	@echo "Running pylint..."
	pylint py_rotator_daily.py py_db_auth.py --max-line-length=120 || true
	@echo "✅ Linting complete"

type-check:
	@echo "Running mypy type checker..."
	mypy . --ignore-missing-imports --exclude=venv --exclude=env || true
	@echo "✅ Type checking complete"

test:
	@echo "Running tests with coverage..."
	pytest -v --cov=. --cov-report=term --cov-report=html
	@echo "✅ Tests complete - see htmlcov/index.html for coverage report"

check: format lint type-check test
	@echo "Running pre-commit hooks..."
	pre-commit run --all-files || true
	@echo "✅ All checks complete"

# Security
security:
	@echo "Running safety check..."
	safety check || true
	@echo "Running bandit security scan..."
	bandit -r . -f json -o bandit-report.json || true
	@echo "✅ Security scans complete - see bandit-report.json"

check-secrets:
	@echo "Checking for exposed secrets..."
	@if git ls-files | grep -E '\.env$$|.*\.ini$$' | grep -v '\.example$$'; then \
		echo "❌ ERROR: Sensitive files found in git!"; \
		exit 1; \
	else \
		echo "✅ No sensitive files in git"; \
	fi

# Maintenance
clean:
	@echo "Cleaning temporary files..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
	find . -type f -name '*.pyo' -delete
	find . -type f -name '*.pyd' -delete
	find . -type f -name '.coverage' -delete
	rm -rf htmlcov/ build/ dist/ *.egg-info
	rm -f bandit-report.json
	@echo "✅ Cleaned temporary files"

clean-all: clean
	@echo "⚠️  This will remove the virtual environment"
	@read -p "Continue? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		rm -rf venv env .venv ENV; \
		echo "✅ Deep clean complete"; \
	else \
		echo "Cancelled"; \
	fi

# Application
run:
	@if [ ! -f configfiles/SocialMediaConfig.ini ]; then \
		echo "❌ Configuration file not found"; \
		echo "Run 'make setup-dev' first"; \
		exit 1; \
	fi
	python py_rotator_daily.py configfiles/SocialMediaConfig.ini

auth:
	@if [ ! -f .env ]; then \
		echo "❌ .env file not found"; \
		echo "Run 'make setup-dev' first"; \
		exit 1; \
	fi
	python py_db_auth.py .env

# Development helpers
watch-test:
	@echo "Watching for changes and running tests..."
	pytest-watch -v

docs:
	@echo "Opening documentation..."
	@open docs/DOCUMENTATION.md || xdg-open docs/DOCUMENTATION.md || echo "Please open docs/DOCUMENTATION.md manually"

status:
	@echo "Project Status:"
	@echo ""
	@echo "Git Status:"
	@git status --short || echo "Not a git repository"
	@echo ""
	@echo "Virtual Environment:"
	@if [ -n "$$VIRTUAL_ENV" ]; then echo "✅ Active: $$VIRTUAL_ENV"; else echo "❌ Not activated"; fi
	@echo ""
	@echo "Configuration Files:"
	@if [ -f .env ]; then echo "✅ .env exists"; else echo "❌ .env missing"; fi
	@if [ -f configfiles/SocialMediaConfig.ini ]; then echo "✅ Config exists"; else echo "❌ Config missing"; fi
	@echo ""
	@echo "Dependencies:"
	@pip list | grep -E "dropbox|openai|replicate|telegram|instagrapi" || echo "Dependencies not installed"

