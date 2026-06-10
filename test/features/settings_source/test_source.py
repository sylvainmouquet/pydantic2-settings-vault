import logging

import pytest
from pydantic import Field, SecretStr
from pydantic_core._pydantic_core import ValidationError

from pydantic2_settings_vault.features.settings_source.source import VaultConfigSettingsSource
from test.features.settings_source.settings import (
    AppSettings,
    InvalidAppSettings,
    ValidAppSettings,
    get_invalid_app_settings,
    get_valid_app_settings,
)
from test.features.shared.vault_mocks import patch_internal_http_vault


class MultiFieldAppSettings(AppSettings):
    FOO: SecretStr = Field(
        ...,
        json_schema_extra={
            "vault_secret_path": "secret/data/test",
            "vault_secret_key": "FOO",
        },
    )
    BAR: SecretStr = Field(
        ...,
        json_schema_extra={
            "vault_secret_path": "secret/data/test",
            "vault_secret_key": "BAR",
        },
    )


class IncompleteMetadataSettings(AppSettings):
    FOO: SecretStr = Field(
        ...,
        json_schema_extra={
            "vault_secret_path": "secret/data/test",
        },
    )


def configure_token_auth(monkeypatch) -> None:
    monkeypatch.setenv("VAULT_AUTH_METHOD", "token")
    monkeypatch.setenv("VAULT_TOKEN", "root-token")
    monkeypatch.delenv("VAULT_ROLE_ID", raising=False)
    monkeypatch.delenv("VAULT_SECRET_ID", raising=False)


def test_get_field_vault_metadata_requires_path_and_key():
    field = IncompleteMetadataSettings.model_fields["FOO"]

    with pytest.raises(ValueError, match="vault_secret_key"):
        VaultConfigSettingsSource._get_field_vault_metadata("FOO", field)


def test_get_field_value_returns_field_name():
    field = ValidAppSettings.model_fields["FOO"]
    source = VaultConfigSettingsSource(settings_cls=ValidAppSettings)

    value, field_name, value_is_complex = source.get_field_value(field, "FOO")

    assert value == "test"
    assert field_name == "FOO"
    assert value_is_complex is False


def test_prepare_field_value_returns_value_unchanged():
    source = VaultConfigSettingsSource(settings_cls=ValidAppSettings)
    field = ValidAppSettings.model_fields["FOO"]

    assert source.prepare_field_value("FOO", field, "secret-value", False) == "secret-value"


def test_source_loads_mapped_secret_from_mocked_vault(mocker, monkeypatch):
    configure_token_auth(monkeypatch)
    get_valid_app_settings.cache_clear()
    patch_internal_http_vault(
        mocker,
        secrets={"FOO": SecretStr("BAR")},
    )

    settings = ValidAppSettings()  # type: ignore

    assert settings.FOO.get_secret_value() == "BAR"


def test_source_missing_secret_key_logs_and_fails_validation(
    mocker,
    monkeypatch,
    caplog,
):
    configure_token_auth(monkeypatch)
    get_invalid_app_settings.cache_clear()
    caplog.set_level(logging.ERROR, logger="pydantic2-settings-vault")
    patch_internal_http_vault(
        mocker,
        secrets={"FOO": SecretStr("BAR")},
    )

    with pytest.raises(ValidationError):
        InvalidAppSettings()  # type: ignore

    assert "UNKNOWN" in caplog.text
    assert "secret/data/test" in caplog.text


def test_source_authentication_failure_propagates(mocker, monkeypatch):
    configure_token_auth(monkeypatch)
    get_valid_app_settings.cache_clear()
    patch_internal_http_vault(
        mocker,
        enter_side_effect=ValueError("Failed to authenticate with Vault token"),
    )

    with pytest.raises(ValueError, match="Failed to authenticate with Vault token"):
        ValidAppSettings()  # type: ignore


def test_source_secret_fetch_failure_propagates(mocker, monkeypatch):
    configure_token_auth(monkeypatch)
    get_valid_app_settings.cache_clear()
    patch_internal_http_vault(
        mocker,
        get_secrets_side_effect=ValueError(
            "Failed to retrieve secret from Vault path 'secret/data/test'"
        ),
    )

    with pytest.raises(
        ValueError,
        match="Failed to retrieve secret from Vault path 'secret/data/test'",
    ):
        ValidAppSettings()  # type: ignore


def test_source_network_failure_propagates(mocker, monkeypatch):
    configure_token_auth(monkeypatch)
    get_valid_app_settings.cache_clear()
    patch_internal_http_vault(
        mocker,
        get_secrets_side_effect=ConnectionError("connection refused"),
    )

    with pytest.raises(ConnectionError, match="connection refused"):
        ValidAppSettings()  # type: ignore


def test_source_fetches_shared_vault_path_once(mocker, monkeypatch):
    configure_token_auth(monkeypatch)
    vault_instance = patch_internal_http_vault(
        mocker,
        secrets={
            "FOO": SecretStr("foo-value"),
            "BAR": SecretStr("bar-value"),
        },
    )

    settings = MultiFieldAppSettings()  # type: ignore

    assert settings.FOO.get_secret_value() == "foo-value"
    assert settings.BAR.get_secret_value() == "bar-value"
    vault_instance.get_secrets.assert_awaited_once()


def test_source_raises_for_incomplete_field_metadata(monkeypatch):
    configure_token_auth(monkeypatch)

    with pytest.raises(ValueError, match="vault_secret_key"):
        IncompleteMetadataSettings()  # type: ignore
