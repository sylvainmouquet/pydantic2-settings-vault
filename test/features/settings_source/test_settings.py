import logging
import os

from loguru import logger
import pytest
from pydantic import Field, SecretStr
from pydantic_core._pydantic_core import ValidationError

from test.features.settings_source.conftest import (
    configure_vault_env,
    configure_vault_token_env,
    parse_vault_credentials,
    VAULT_DEV_ROOT_TOKEN,
)
from test.features.settings_source.settings import (
    AppSettings,
    ValidAppSettings,
    get_invalid_app_settings,
    get_valid_app_settings,
)


class LogicalPathAppSettings(AppSettings):
    FOO: SecretStr = Field(
        ...,
        json_schema_extra={
            "vault_secret_path": "secret/test",
            "vault_secret_key": "FOO",
        },
    )


class Kv1AppSettings(AppSettings):
    FOO: SecretStr = Field(
        ...,
        json_schema_extra={
            "vault_secret_path": "secretv1/test",
            "vault_secret_key": "FOO",
        },
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


@pytest.mark.asyncio
async def test_valid_get_secret_with_token_auth(
    disable_logging_exception, vault_container
):
    credentials = vault_container.execute(["cat", "/vault-credentials.env"])
    credentials_dict = parse_vault_credentials(credentials)
    configure_vault_token_env(vault_container, credentials_dict)

    vault_container.execute(
        ["vault", "kv", "put", "-mount=secret", "test", "FOO=BAR"],
    )

    get_valid_app_settings.cache_clear()
    settings: ValidAppSettings = get_valid_app_settings()
    assert settings.FOO.get_secret_value() == "BAR"


@pytest.mark.asyncio
async def test_valid_get_secret_with_logical_kv2_path(
    disable_logging_exception, vault_container
):
    credentials = vault_container.execute(["cat", "/vault-credentials.env"])
    credentials_dict = parse_vault_credentials(credentials)
    configure_vault_env(vault_container, credentials_dict)
    os.environ.pop("VAULT_KV_VERSION", None)

    vault_container.execute(
        ["vault", "kv", "put", "-mount=secret", "test", "FOO=BAR"],
    )

    settings = LogicalPathAppSettings()  # type: ignore
    assert settings.FOO.get_secret_value() == "BAR"


@pytest.mark.asyncio
async def test_valid_get_secret_with_kv_v1_mount(
    disable_logging_exception, vault_container
):
    credentials = vault_container.execute(["cat", "/vault-credentials.env"])
    credentials_dict = parse_vault_credentials(credentials)
    configure_vault_token_env(vault_container, credentials_dict)
    previous_kv_version = os.environ.get("VAULT_KV_VERSION")
    os.environ["VAULT_KV_VERSION"] = "1"
    os.environ["VAULT_TOKEN"] = VAULT_DEV_ROOT_TOKEN

    try:
        vault_container.execute(
            ["vault", "secrets", "enable", "-path=secretv1", "-version=1", "kv"],
        )
        vault_container.execute(
            ["vault", "kv", "put", "-mount=secretv1", "test", "FOO=BAR"],
        )

        settings = Kv1AppSettings()  # type: ignore
        assert settings.FOO.get_secret_value() == "BAR"
    finally:
        if previous_kv_version is None:
            os.environ.pop("VAULT_KV_VERSION", None)
        else:
            os.environ["VAULT_KV_VERSION"] = previous_kv_version
