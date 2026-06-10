set shell := ["bash", "-cu"]

default:
    @just --list

# Git workflow commands
wip:
    git add .
    git commit -m "WIP: Work in progress"
    git push

# Install command
install:
    uv sync --all-extras --dev

# Build command
build: check-version
    rm -rf dist/* || true
    ./scripts/version.sh "${VERSION}"
    @grep version pyproject.toml
    @grep version pydantic2_settings_vault/__init__.py
    uv build

check-version:
    @if [ -z "${VERSION:-}" ]; then \
        echo "VERSION is not set. Please set the VERSION environment variable."; \
        exit 1; \
    fi

# Deploy command
deploy:
    uvx twine upload dist/*

# Install local build command
install-local:
    pip3 install dist/*.whl

# Test command
test *args:
    uv run --python ${PYTHON_VERSION:-3.14} pytest -v --log-cli-level=INFO {{args}}

# Coverage command (100% threshold per project policy)
coverage *args:
    uv run --python ${PYTHON_VERSION:-3.14} pytest \
        --cov=pydantic2_settings_vault \
        --cov-report=term-missing \
        --cov-fail-under=100 \
        -v {{args}}

# Format command
format:
    uv run ruff check --fix
    uv run ruff format

# Lint command
lint:
    uv run ruff check
    uv run ruff format --check

# Run lint, type-check, and tests
check: lint type-check test

# Update dependencies
update:
    uv lock --upgrade
    uv sync

# Check for outdated dependencies
check-deps:
    .venv/bin/pip list --outdated

# Run type checking
type-check:
    PYRIGHT_PYTHON_FORCE_VERSION=latest uv run pyright

# Build user documentation (MkDocs)
docs-build:
    uv run mkdocs build --strict

# Serve user documentation locally
docs-serve:
    uv run mkdocs serve

# Deploy documentation to GitHub Pages (requires gh auth)
docs-deploy:
    uv run mkdocs gh-deploy --force
