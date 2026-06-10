import time
from typing import Tuple, Type

import pytest
from pydantic import Field, SecretStr
from pydantic_core._pydantic_core import ValidationError
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

from pydantic2_settings_vault.features.settings_source.cache import (
    VaultSecretCache,
    reset_shared_secret_cache,
)
from pydantic2_settings_vault.features.settings_source.source import (
    VaultConfigSettingsSource,
)
from test.features.settings_source.settings import AppSettings, ValidAppSettings

EXPLICIT_SECRET_CACHE = VaultSecretCache(ttl_seconds=60)
from test.features.settings_source.test_source import configure_token_auth
from test.features.shared.vault_mocks import patch_internal_http_vault


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_shared_secret_cache()
    yield
    reset_shared_secret_cache()


def test_vault_secret_cache_stores_and_returns_entries():
    cache = VaultSecretCache(ttl_seconds=60)
    secrets = {"FOO": SecretStr("bar")}

    cache.set("secret/data/test", 2, secrets)

    assert cache.get("secret/data/test", 2) == secrets
    assert cache.get("secret/data/other", 2) is None


def test_vault_secret_cache_expires_after_ttl():
    cache = VaultSecretCache(ttl_seconds=0.05)
    secrets = {"FOO": SecretStr("bar")}
    cache.set("secret/data/test", 2, secrets)

    time.sleep(0.06)

    assert cache.get("secret/data/test", 2) is None


def test_vault_secret_cache_without_ttl_never_expires():
    cache = VaultSecretCache()
    secrets = {"FOO": SecretStr("bar")}
    cache.set("secret/data/test", 2, secrets)

    assert cache.get("secret/data/test", 2) == secrets


class CachedAppSettings(ValidAppSettings):
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            VaultConfigSettingsSource(
                settings_cls=settings_cls,
                cache_enabled=True,
                cache_ttl_seconds=60,
            ),
        )


class ExplicitCacheAppSettings(ValidAppSettings):
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            VaultConfigSettingsSource(
                settings_cls=settings_cls,
                secret_cache=EXPLICIT_SECRET_CACHE,
            ),
        )


class IntFieldAppSettings(AppSettings):
    COUNT: int = Field(
        ...,
        json_schema_extra={
            "vault_secret_path": "secret/data/test",
            "vault_secret_key": "COUNT",
        },
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            VaultConfigSettingsSource(
                settings_cls=settings_cls,
                cache_enabled=True,
            ),
        )


def test_source_cache_disabled_by_default_fetches_on_every_load(mocker, monkeypatch):
    configure_token_auth(monkeypatch)
    vault_instance = patch_internal_http_vault(
        mocker,
        secrets={"FOO": SecretStr("BAR")},
    )

    ValidAppSettings()  # type: ignore
    ValidAppSettings()  # type: ignore

    assert vault_instance.get_secrets.await_count == 2


def test_source_cache_enabled_avoids_repeat_fetch(mocker, monkeypatch):
    configure_token_auth(monkeypatch)
    vault_instance = patch_internal_http_vault(
        mocker,
        secrets={"FOO": SecretStr("BAR")},
    )

    CachedAppSettings()  # type: ignore
    CachedAppSettings()  # type: ignore

    vault_instance.get_secrets.assert_awaited_once()


def test_source_explicit_secret_cache_is_shared_across_loads(mocker, monkeypatch):
    configure_token_auth(monkeypatch)
    vault_instance = patch_internal_http_vault(
        mocker,
        secrets={"FOO": SecretStr("BAR")},
    )
    EXPLICIT_SECRET_CACHE.clear()

    ExplicitCacheAppSettings()  # type: ignore
    ExplicitCacheAppSettings()  # type: ignore

    vault_instance.get_secrets.assert_awaited_once()


def test_source_cache_ttl_triggers_refetch(mocker, monkeypatch):
    configure_token_auth(monkeypatch)
    vault_instance = patch_internal_http_vault(
        mocker,
        secrets={"FOO": SecretStr("BAR")},
    )

    class ShortTtlCachedAppSettings(ValidAppSettings):
        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: Type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return (
                init_settings,
                env_settings,
                dotenv_settings,
                VaultConfigSettingsSource(
                    settings_cls=settings_cls,
                    cache_enabled=True,
                    cache_ttl_seconds=0.05,
                ),
            )

    ShortTtlCachedAppSettings()  # type: ignore
    time.sleep(0.06)
    ShortTtlCachedAppSettings()  # type: ignore

    assert vault_instance.get_secrets.await_count == 2


def test_cached_invalid_value_still_fails_pydantic_validation(mocker, monkeypatch):
    configure_token_auth(monkeypatch)
    patch_internal_http_vault(
        mocker,
        secrets={"COUNT": SecretStr("not-a-number")},
    )

    with pytest.raises(ValidationError):
        IntFieldAppSettings()  # type: ignore

    with pytest.raises(ValidationError):
        IntFieldAppSettings()  # type: ignore
