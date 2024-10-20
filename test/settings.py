from functools import lru_cache
from threading import Lock
from typing import Tuple, Type

from pydantic import Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
)

from pydantic2_settings_vault import VaultConfigSettingsSource

# env_file: str = ".env.test" if "PYTEST_VERSION" in os.environ else f".env"


class AppSettings(BaseSettings):
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
            VaultConfigSettingsSource(settings_cls=settings_cls),
        )


class ValidAppSettings(AppSettings):
    # model_config = SettingsConfigDict(env_file=env_file, extra="ignore")

    FOO: SecretStr = Field(
        ...,
        json_schema_extra={
            "vault_secret_path": "secret/data/test",
            "vault_secret_key": "FOO",  # pragma: allowlist secret
        },
    )


class InvalidAppSettings(AppSettings):
    UNKNOWN: SecretStr = Field(
        ...,
        json_schema_extra={
            "vault_secret_path": "secret/data/test",
            "vault_secret_key": "UNKNOWN",  # pragma: allowlist secret
        },
    )


app_settings_lock = Lock()


@lru_cache
def get_valid_app_settings() -> ValidAppSettings:
    with app_settings_lock:
        return ValidAppSettings()  # type: ignore


@lru_cache
def get_invalid_app_settings() -> InvalidAppSettings:
    with app_settings_lock:
        return InvalidAppSettings()  # type: ignore
