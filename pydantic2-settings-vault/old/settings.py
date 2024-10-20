import json
import logging
import logging.handlers
import os
import sys
from enum import Enum
from functools import lru_cache
from threading import Lock
from typing import Any, Tuple, Type

from pydantic import Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

env_file: str = ".env.test" if "PYTEST_VERSION" in os.environ else f".env"

class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=env_file, extra="ignore")

    # https://hub.docker.com/r/hashicorp/vault/tags
    TEST_VAULT_DOCKER_IMAGE: str = "docker.io/hashicorp/vault:1.17.3"

    VAULT_URL: str = Field(default="https://vault.idum.cloud")

    AES_KEY: SecretStr = Field(
        ...,
        json_schema_extra={
            "vault_secret_path": f"secrets/data",
            "vault_secret_key": "AES_KEY",  # pragma: allowlist secret
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
            VaultConfigSettingsSource(settings_cls=settings_cls),
        )

app_settings_lock = Lock()

@lru_cache
# @logfire.instrument("Load settings", extract_args=True)
def get_app_settings() -> AppSettings:
    with app_settings_lock:
        return AppSettings()  # type: ignore
