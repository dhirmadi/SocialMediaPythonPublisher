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
	@echo "  make export-reqs     Export requirements.txt from Poetry"
	@echo "  make export-reqs-dev Export requirements-dev.txt (incl. dev) from Poetry"
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
	@echo "  make run-v2          Run V2 application (publisher_v2)"
	@echo "  make preview-v2      Preview V2 without publishing (CONFIG=file.ini)"

# Installation
install:
	poetry install --no-root

install-dev:
	poetry install --no-root

setup-dev: install-dev
	@echo "Setting up pre-commit hooks..."
	@poetry run pre-commit --version >/dev/null 2>&1 && poetry run pre-commit install || echo "Skipping pre-commit (not available for this Python)"
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

# Export pip requirement files for non-Poetry environments
export-reqs:
	@echo "Exporting requirements.txt from Poetry..."
	@if ! poetry help | grep -q 'export'; then \
		echo "Poetry export plugin not found. Installing poetry-plugin-export..."; \
		poetry self add poetry-plugin-export || { echo "Failed to install poetry-plugin-export. Please install it manually."; exit 1; }; \
	fi
	poetry export -f requirements.txt --output requirements.txt --without-hashes
	@echo "✅ requirements.txt updated"

export-reqs-dev:
	@echo "Exporting requirements-dev.txt (includes dev deps) from Poetry..."
	@if ! poetry help | grep -q 'export'; then \
		echo "Poetry export plugin not found. Installing poetry-plugin-export..."; \
		poetry self add poetry-plugin-export || { echo "Failed to install poetry-plugin-export. Please install it manually."; exit 1; }; \
	fi
	poetry export -f requirements.txt --with dev --output requirements-dev.txt --without-hashes
	@echo "✅ requirements-dev.txt updated"

# Code Quality
format:
	@echo "Formatting code with black..."
	poetry run black . --line-length 120
	@echo "Sorting imports with isort..."
	poetry run isort . --profile black --line-length 120
	@echo "✅ Code formatted"

lint:
	@echo "Running flake8..."
	poetry run flake8 . --max-line-length=120 --extend-ignore=E203,E501 --exclude=venv,env,.venv,.git,__pycache__
	@echo "Running pylint..."
	poetry run pylint py_rotator_daily.py py_db_auth.py --max-line-length=120 || true
	@echo "✅ Linting complete"

type-check:
	@echo "Running mypy type checker..."
	poetry run mypy . --ignore-missing-imports --exclude=venv --exclude=env || true
	@echo "✅ Type checking complete"

test:
	@echo "Running tests with coverage..."
	poetry run pytest -v --cov=. --cov-report=term --cov-report=html
	@echo "✅ Tests complete - see htmlcov/index.html for coverage report"

check: format lint type-check test
	@echo "Running pre-commit hooks..."
	@poetry run pre-commit --version >/dev/null 2>&1 && poetry run pre-commit run --all-files || echo "Skipping pre-commit run (not available)"
	@echo "✅ All checks complete"

# Security
security:
	@echo "Running safety check..."
	poetry run safety check || true
	@echo "Running bandit security scan..."
	poetry run bandit -r . -f json -o bandit-report.json || true
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
	poetry run python py_rotator_daily.py configfiles/SocialMediaConfig.ini

run-v2:
	@if [ ! -f code_v1/configfiles/SocialMediaConfig.ini ] && [ ! -f configfiles/SocialMediaConfig.ini ]; then \
		echo "❌ Configuration file not found (code_v1/configfiles/SocialMediaConfig.ini or configfiles/SocialMediaConfig.ini)"; \
		exit 1; \
	fi; \
	CONFIG_PATH=$$( [ -f configfiles/SocialMediaConfig.ini ] && echo "configfiles/SocialMediaConfig.ini" || echo "code_v1/configfiles/SocialMediaConfig.ini" ); \
	PYTHONPATH=publisher_v2/src poetry run python publisher_v2/src/publisher_v2/app.py --config $$CONFIG_PATH

preview-v2:
	@if [ -z "$(CONFIG)" ]; then \
		echo "❌ CONFIG variable required. Usage: make preview-v2 CONFIG=configfiles/fetlife.ini"; \
		exit 1; \
	fi; \
	if [ ! -f "$(CONFIG)" ]; then \
		echo "❌ Configuration file not found: $(CONFIG)"; \
		exit 1; \
	fi; \
	echo "🔍 Running preview mode with $(CONFIG)..."; \
	PYTHONPATH=publisher_v2/src poetry run python publisher_v2/src/publisher_v2/app.py --config $(CONFIG) --preview

auth:
	@if [ ! -f .env ]; then \
		echo "❌ .env file not found"; \
		echo "Run 'make setup-dev' first"; \
		exit 1; \
	fi
	poetry run python py_db_auth.py .env

# Development helpers
watch-test:
	@echo "Watching for changes and running tests..."
	poetry run pytest-watch -v

docs:
	@echo "Opening documentation..."
	@open docs_v2/README.md || xdg-open docs_v2/README.md || echo "Please open docs_v2/README.md manually"

status:
	@echo "Project Status:"
	@echo ""
	@echo "Git Status:"
	@git status --short || echo "Not a git repository"
	@echo ""
	@echo "Virtual Environment:"
	@poetry env info --path >/dev/null 2>&1 && echo "✅ Poetry venv: $$(poetry env info --path)" || echo "❌ Poetry venv not created"
	@echo ""
	@echo "Configuration Files:"
	@if [ -f .env ]; then echo "✅ .env exists"; else echo "❌ .env missing"; fi
	@if [ -f configfiles/SocialMediaConfig.ini ]; then echo "✅ Config exists"; else echo "❌ Config missing"; fi
	@echo ""
	@echo "Dependencies:"
	@poetry show -q | grep -E "dropbox|openai|telegram|instagrapi" || echo "Dependencies not installed"

