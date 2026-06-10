import logging

from loguru import logger
import pytest
from pydantic_core._pydantic_core import ValidationError

from test.features.settings_source.conftest import (
    configure_vault_env,
    parse_vault_credentials,
)
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
    credentials_dict = parse_vault_credentials(credentials)
    configure_vault_env(vault_container, credentials_dict)

    vault_container.execute(
        ["vault", "kv", "put", "-mount=secret", "test", "FOO=BAR"],
    )

    settings: ValidAppSettings = get_valid_app_settings()
    assert settings.FOO.get_secret_value() == "BAR"
    logger.info("Secret Found")


@pytest.mark.asyncio
async def test_invalid_get_secret(disable_logging_exception, vault_container, caplog):
    caplog.set_level(logging.ERROR, logger="pydantic2-settings-vault")

    # Read the vault credentials from the file
    credentials = vault_container.execute(["cat", "/vault-credentials.env"])
    credentials_dict = parse_vault_credentials(credentials)
    configure_vault_env(vault_container, credentials_dict)

    vault_container.execute(
        ["vault", "kv", "put", "-mount=secret", "test", "FOO=BAR"],
    )

    with pytest.raises(ValidationError):
        # the secret UNKNOWN is not found
        get_invalid_app_settings()

    assert "UNKNOWN" in caplog.text
    assert "secret/data/test" in caplog.text
    assert "BAR" not in caplog.text
