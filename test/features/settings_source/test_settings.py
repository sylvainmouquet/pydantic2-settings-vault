import logging
import os

from loguru import logger
import pytest
from pydantic_core._pydantic_core import ValidationError

from test.features.settings_source.settings import (
    ValidAppSettings,
    get_invalid_app_settings,
    get_valid_app_settings,
)


def test_missing_vault_credentials_error_mentions_required_env_vars(monkeypatch):
    monkeypatch.delenv("VAULT_ROLE_ID", raising=False)
    monkeypatch.delenv("VAULT_SECRET_ID", raising=False)

    with pytest.raises(ValueError) as exc_info:
        ValidAppSettings()  # type: ignore

    error_message = str(exc_info.value)
    assert "Missing required Vault environment variables" in error_message
    assert "VAULT_ROLE_ID" in error_message
    assert "VAULT_SECRET_ID" in error_message


@pytest.mark.asyncio
async def test_valid_get_secret(disable_logging_exception, vault_container):
    # Read the vault credentials from the file
    credentials = vault_container.execute(["cat", "/vault-credentials.env"])
    credentials_dict = dict(line.split("=") for line in credentials.splitlines())
    role_id = credentials_dict.get("ROLE_ID")
    secret_id = credentials_dict.get("SECRET_ID")

    os.environ["VAULT_ROLE_ID"] = role_id
    os.environ["VAULT_SECRET_ID"] = secret_id

    vault_container.execute(
        ["vault", "kv", "put", "-mount=secret", "test", "FOO=BAR"],
        envs={"VAULT_ADDR": "http://127.0.0.1:8200"},
    )

    settings: ValidAppSettings = get_valid_app_settings()
    assert settings.FOO.get_secret_value() == "BAR"
    logger.info("Secret Found")


@pytest.mark.asyncio
async def test_invalid_get_secret(disable_logging_exception, vault_container, caplog):
    caplog.set_level(logging.ERROR, logger="pydantic2-settings-vault")

    # Read the vault credentials from the file
    credentials = vault_container.execute(["cat", "/vault-credentials.env"])
    credentials_dict = dict(line.split("=") for line in credentials.splitlines())
    role_id = credentials_dict.get("ROLE_ID")
    secret_id = credentials_dict.get("SECRET_ID")

    os.environ["VAULT_ROLE_ID"] = role_id
    os.environ["VAULT_SECRET_ID"] = secret_id

    vault_container.execute(
        ["vault", "kv", "put", "-mount=secret", "test", "FOO=BAR"],
        envs={"VAULT_ADDR": "http://127.0.0.1:8200"},
    )

    with pytest.raises(ValidationError):
        # the secret UNKNOWN is not found
        get_invalid_app_settings()

    assert "UNKNOWN" in caplog.text
    assert "secret/data/test" in caplog.text
    assert "BAR" not in caplog.text
