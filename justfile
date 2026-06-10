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

# Lint command
lint:
    uv run ruff check --fix
    uv run ruff format
    uv run ruff format --check

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
