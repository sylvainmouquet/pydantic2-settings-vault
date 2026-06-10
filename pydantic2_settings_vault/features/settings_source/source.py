import asyncio
import concurrent.futures
import logging
import os
from typing import Any, Tuple

from concurrency_limiter import concurrency_limiter
from pydantic import SecretStr
from pydantic.fields import FieldInfo
from pydantic_settings import PydanticBaseSettingsSource
from reattempt import reattempt

from pydantic2_settings_vault.features.authentication.registry import (
    get_auth_backend_from_env,
    get_required_env_vars_for_method,
    resolve_auth_method,
)
from pydantic2_settings_vault.features.settings_source.cache import (
    VaultSecretCache,
    get_shared_secret_cache,
)
from pydantic2_settings_vault.shared.infrastructure.kv_paths import (
    normalize_kv_path,
    resolve_kv_version,
    resolve_kv_version_from_env,
)
from pydantic2_settings_vault.shared.infrastructure.vault_client_config import (
    VaultClientConfig,
)
from pydantic2_settings_vault.shared.infrastructure.vault_http import InternalHttpVault

logger = logging.getLogger("pydantic2-settings-vault")
logger.addHandler(logging.NullHandler())


class VaultConfigSettingsSource(PydanticBaseSettingsSource):
    CONST_HEADER_X_VAULT_TOKEN: str = "X-Vault-Token"

    def __init__(
        self,
        settings_cls,
        *,
        client_config: VaultClientConfig | None = None,
        cache_enabled: bool = False,
        cache_ttl_seconds: float | None = None,
        secret_cache: VaultSecretCache | None = None,
    ) -> None:
        super().__init__(settings_cls)
        self._client_config = client_config or VaultClientConfig()
        if secret_cache is not None:
            self._secret_cache = secret_cache
        elif cache_enabled:
            self._secret_cache = get_shared_secret_cache(ttl_seconds=cache_ttl_seconds)
        else:
            self._secret_cache = None

    @classmethod
    def _get_auth_backend(cls):
        missing_env_vars = [
            env_var
            for env_var in get_required_env_vars_for_method()
            if not os.getenv(env_var)
        ]

        if missing_env_vars:
            missing_env_vars_text = ", ".join(missing_env_vars)
            auth_method = resolve_auth_method()
            raise ValueError(
                "Missing required Vault environment variables: "
                f"{missing_env_vars_text}. Configure {auth_method} auth credentials "
                "before loading Vault-backed settings."
            )

        return get_auth_backend_from_env()

    @staticmethod
    def _get_field_vault_metadata(field_name: str, field: FieldInfo) -> tuple[str, str]:
        field_metadata = field.json_schema_extra or {}
        missing_metadata = [
            metadata_key
            for metadata_key in ("vault_secret_path", "vault_secret_key")
            if not field_metadata.get(metadata_key)
        ]

        if missing_metadata:
            missing_metadata_text = ", ".join(missing_metadata)
            raise ValueError(
                "Vault metadata for settings field "
                f"'{field_name}' is incomplete. Missing: {missing_metadata_text}."
            )

        return (
            str(field_metadata["vault_secret_path"]),
            str(field_metadata["vault_secret_key"]),
        )

    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> Tuple[Any, str, bool]:
        field_value = "test"
        # print(field.json_schema_extra)
        return field_value, field_name, False

    def prepare_field_value(
        self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool
    ) -> Any:
        return value

    def __call__(self) -> dict[str, Any]:
        vault_url: str = os.getenv("VAULT_URL", default="http://127.0.0.1:8200")
        vault_namespace: str | None = os.getenv("VAULT_NAMESPACE")
        auth_backend = self._get_auth_backend()
        default_kv_version = resolve_kv_version_from_env()

        d: dict[str, Any] = {}

        async def _get_vault_fetch_targets() -> list[tuple[str, int]]:
            """Collect unique Vault paths to fetch, normalized per KV version."""
            fetch_targets: dict[tuple[str, int], None] = {}
            for _fieldname, field in filter(
                lambda item: item[1].json_schema_extra,
                self.settings_cls.model_fields.items(),
            ):
                vault_path, _vault_secret_key = self._get_field_vault_metadata(
                    field_name=_fieldname, field=field
                )
                field_metadata = field.json_schema_extra
                metadata_dict = (
                    field_metadata if isinstance(field_metadata, dict) else {}
                )
                kv_version = resolve_kv_version(
                    metadata_dict,
                    default=default_kv_version,
                )
                normalized_path = normalize_kv_path(vault_path, kv_version)
                fetch_targets[(normalized_path, kv_version)] = None

            return list(fetch_targets.keys())

        secret_cache = self._secret_cache
        client_config = self._client_config

        @concurrency_limiter(max_concurrent=client_config.max_concurrent_requests)
        async def _get_vault_secrets(
            _vault: InternalHttpVault,
            vault_path: str,
            kv_version: int,
        ) -> dict[str, SecretStr]:
            if secret_cache is not None:
                cached_secrets = secret_cache.get(vault_path, kv_version)
                if cached_secrets is not None:
                    return cached_secrets

            secrets = await _vault.get_secrets(
                vault_path=vault_path,
                kv_version=kv_version,
            )
            if secret_cache is not None:
                secret_cache.set(vault_path, kv_version, secrets)
            return secrets

        @reattempt(
            max_retries=client_config.retry_max_attempts,
            min_time=client_config.retry_min_delay,
            max_time=client_config.retry_max_delay,
        )
        async def get_secrets():
            k: dict[str, Any] = {}

            async with InternalHttpVault(
                url=vault_url,
                namespace=vault_namespace,
                auth_backend=auth_backend,
                default_kv_version=default_kv_version,
                client_config=client_config,
            ) as vault:
                fetch_targets = await _get_vault_fetch_targets()
                vault_secrets_list: list[dict[str, SecretStr]] = await asyncio.gather(
                    *[
                        _get_vault_secrets(
                            _vault=vault,
                            vault_path=vault_path,
                            kv_version=kv_version,
                        )
                        for vault_path, kv_version in fetch_targets
                    ]
                )

            # Converting the list of dictionaries to a single dictionary
            vault_secrets_dict: dict[str, SecretStr] = {}
            for vault_secrets in vault_secrets_list:
                vault_secrets_dict.update(vault_secrets)

            for field_name, field in filter(
                lambda item: item[1].json_schema_extra,
                self.settings_cls.model_fields.items(),
            ):
                vault_path, vault_secret_key = self._get_field_vault_metadata(
                    field_name=field_name, field=field
                )

                if vault_secret_key in vault_secrets_dict:
                    k[field_name] = vault_secrets_dict[
                        vault_secret_key
                    ].get_secret_value()
                else:
                    logger.error(
                        "Vault secret key %r for settings field %r was not found "
                        "at Vault path %r",
                        vault_secret_key,
                        field_name,
                        vault_path,
                    )
            return k

        def run_async_method():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(get_secrets())  # type: ignore
            loop.close()
            return result

        # Create a thread and run the async method
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(run_async_method)

        # Wait for the thread to complete and get the result
        d = future.result()

        return d
