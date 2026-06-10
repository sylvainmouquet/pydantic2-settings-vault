import pytest
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings

from pydantic2_settings_vault import validate_vault_configuration
from test.features.settings_source.conftest import (
    configure_vault_env,
    parse_vault_credentials,
)
from test.features.settings_source.settings import AppSettings, ValidAppSettings


class IncompleteMetadataSettings(AppSettings):
    FOO: SecretStr = Field(
        ...,
        json_schema_extra={
            "vault_secret_path": "secret/data/test",
        },
    )


class PartialKeyMetadataSettings(AppSettings):
    BAR: SecretStr = Field(
        ...,
        json_schema_extra={
            "vault_secret_key": "BAR",
        },
    )


class NonVaultSettings(BaseSettings):
    PLAIN: str = "value"


def test_validate_reports_missing_env_vars(monkeypatch):
    monkeypatch.delenv("VAULT_ROLE_ID", raising=False)
    monkeypatch.delenv("VAULT_SECRET_ID", raising=False)

    result = validate_vault_configuration(ValidAppSettings)

    assert not result.valid
    assert len(result.errors) == 1
    assert result.errors[0].code == "missing_env_vars"
    assert "VAULT_ROLE_ID" in result.errors[0].message
    assert "VAULT_SECRET_ID" in result.errors[0].message


def test_validate_reports_incomplete_field_metadata(monkeypatch):
    monkeypatch.setenv("VAULT_ROLE_ID", "role-id")
    monkeypatch.setenv("VAULT_SECRET_ID", "secret-id")

    result = validate_vault_configuration(IncompleteMetadataSettings)

    assert not result.valid
    assert len(result.errors) == 1
    assert result.errors[0].code == "incomplete_field_metadata"
    assert result.errors[0].field_name == "FOO"
    assert "vault_secret_key" in result.errors[0].message


def test_validate_reports_missing_path_metadata(monkeypatch):
    monkeypatch.setenv("VAULT_ROLE_ID", "role-id")
    monkeypatch.setenv("VAULT_SECRET_ID", "secret-id")

    result = validate_vault_configuration(PartialKeyMetadataSettings)

    assert not result.valid
    assert result.errors[0].code == "incomplete_field_metadata"
    assert result.errors[0].field_name == "BAR"
    assert "vault_secret_path" in result.errors[0].message


def test_validate_succeeds_for_valid_configuration(monkeypatch):
    monkeypatch.setenv("VAULT_ROLE_ID", "role-id")
    monkeypatch.setenv("VAULT_SECRET_ID", "secret-id")

    result = validate_vault_configuration(ValidAppSettings)

    assert result.valid
    assert result.errors == []


def test_validate_skips_fields_without_vault_metadata():
    result = validate_vault_configuration(NonVaultSettings)

    assert result.valid


def test_raise_if_invalid_raises_for_errors(monkeypatch):
    monkeypatch.setenv("VAULT_ROLE_ID", "role-id")
    monkeypatch.setenv("VAULT_SECRET_ID", "secret-id")

    result = validate_vault_configuration(IncompleteMetadataSettings)

    with pytest.raises(ValueError, match="Vault metadata for settings field 'FOO'"):
        result.raise_if_invalid()


@pytest.mark.asyncio
async def test_validate_auth_check_succeeds(disable_logging_exception, vault_container):
    credentials = vault_container.execute(["cat", "/vault-credentials.env"])
    credentials_dict = parse_vault_credentials(credentials)
    configure_vault_env(vault_container, credentials_dict)

    result = validate_vault_configuration(ValidAppSettings, check_auth=True)

    assert result.valid


@pytest.mark.asyncio
async def test_validate_auth_check_reports_failure(
    disable_logging_exception, vault_container, monkeypatch
):
    credentials = vault_container.execute(["cat", "/vault-credentials.env"])
    credentials_dict = parse_vault_credentials(credentials)
    configure_vault_env(vault_container, credentials_dict)

    monkeypatch.setenv("VAULT_SECRET_ID", "invalid-secret-id")

    result = validate_vault_configuration(ValidAppSettings, check_auth=True)

    assert not result.valid
    assert len(result.errors) == 1
    assert result.errors[0].code == "auth_failed"
    assert "Vault authentication check failed" in result.errors[0].message


def test_validate_skips_auth_check_when_env_vars_missing(monkeypatch):
    monkeypatch.delenv("VAULT_ROLE_ID", raising=False)
    monkeypatch.delenv("VAULT_SECRET_ID", raising=False)

    result = validate_vault_configuration(ValidAppSettings, check_auth=True)

    assert not result.valid
    assert all(error.code != "auth_failed" for error in result.errors)
