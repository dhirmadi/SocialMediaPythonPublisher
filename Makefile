# Makefile for Social Media Python Publisher
# Simplifies common development tasks

.PHONY: help install install-dev format lint type-check test test-cov-file security clean setup-dev

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
	@echo "  make format          Format code and fix lint issues (ruff)"
	@echo "  make lint            Run linter (ruff check)"
	@echo "  make type-check      Run type checker (mypy)"
	@echo "  make test            Run tests with coverage"
	@echo "  make test-cov-file   Coverage for one FILE=... (no 85% gate)"
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
	@echo "  make run-v2          Run V2 application (publisher_v2)"
	@echo "  make preview-v2      Preview V2 without publishing (env-first)"

# Installation
install:
	uv sync

install-dev:
	uv sync --group dev

setup-dev: install-dev
	@echo "Setting up pre-commit hooks..."
	@uv run pre-commit --version >/dev/null 2>&1 && uv run pre-commit install || echo "Skipping pre-commit (not available for this Python)"
	@echo "Creating configuration files from examples..."
	@if [ ! -f .env ]; then cp dotenv.v2.example .env; echo "Created .env - EDIT THIS FILE"; fi
	@echo ""
	@echo "✅ Development environment setup complete!"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Edit .env with your API credentials"
	@echo "  2. Run 'make test' to verify installation"

# Export pip requirement files for non-Poetry environments
export-reqs:
	@echo "Exporting requirements.txt from uv..."
	uv export --format requirements-txt --no-hashes > requirements.txt
	@echo "✅ requirements.txt updated"

export-reqs-dev:
	@echo "Exporting requirements-dev.txt (includes dev deps) from uv..."
	uv export --format requirements-txt --group dev --no-hashes > requirements-dev.txt
	@echo "✅ requirements-dev.txt updated"

# Code Quality
format:
	@echo "Formatting code with ruff..."
	uv run ruff format .
	@echo "Fixing lint issues with ruff..."
	uv run ruff check --fix .
	@echo "✅ Code formatted and lint-fixed"

lint:
	@echo "Running ruff check..."
	uv run ruff check .
	@echo "✅ Linting complete"

type-check:
	@echo "Running mypy type checker..."
	uv run mypy publisher_v2/src --ignore-missing-imports
	@echo "✅ Type checking complete"

test:
	@echo "Running tests with coverage..."
	uv run pytest -v --cov --cov-report=term-missing --cov-report=html
	@echo "✅ Tests complete - see htmlcov/index.html for coverage report"

# Coverage for one file or directory. The 85% gate is a whole-run gate, so a
# partial run has to opt out of it or it fails on everything it did not touch.
test-cov-file:
	@if [ -z "$(FILE)" ]; then echo "Usage: make test-cov-file FILE=publisher_v2/tests/test_x.py"; exit 1; fi
	COVERAGE_FILE=.coverage.partial uv run pytest -v --cov --cov-report=term-missing --cov-fail-under=0 $(FILE)

check: format lint type-check test
	@echo "Running pre-commit hooks..."
	@uv run pre-commit --version >/dev/null 2>&1 && uv run pre-commit run --all-files || echo "Skipping pre-commit run (not available)"
	@echo "✅ All checks complete"

# Security
security:
	@echo "Running safety check..."
	uv run safety check || true
	@echo "Running bandit security scan..."
	uv run bandit -r . -f json -o bandit-report.json || true
	@echo "✅ Security scans complete - see bandit-report.json"

check-secrets:
	@echo "Checking for exposed secrets..."
	@if git ls-files | grep -E '\.env$$|.*\.ini$$' | grep -v '\.example$$' | grep -v '^publisher_v2/alembic\.ini$$'; then \
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
run-v2:
	PYTHONPATH=publisher_v2/src uv run python publisher_v2/src/publisher_v2/app.py

preview-v2:
	@echo "🔍 Running preview mode (env-first config, #97 stage 4)..."
	PYTHONPATH=publisher_v2/src uv run python publisher_v2/src/publisher_v2/app.py --preview

# Development helpers
watch-test:
	@echo "Watching for changes and running tests..."
	uv run pytest-watch -v

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
	@uv run which python >/dev/null 2>&1 && echo "✅ uv venv: $$(uv run which python)" || echo "❌ uv venv not created"
	@echo ""
	@echo "Configuration Files:"
	@if [ -f .env ]; then echo "✅ .env exists"; else echo "❌ .env missing"; fi
	@echo ""
	@echo "Dependencies:"
	@uv pip list -q | grep -E "dropbox|openai|telegram|instagrapi" || echo "Dependencies not installed"
