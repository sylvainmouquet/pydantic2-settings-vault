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
from pydantic2_settings_vault.shared.infrastructure.vault_http import InternalHttpVault

logger = logging.getLogger("pydantic2-settings-vault")
logger.addHandler(logging.NullHandler())


class VaultConfigSettingsSource(PydanticBaseSettingsSource):
    CONST_HEADER_X_VAULT_TOKEN: str = "X-Vault-Token"

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

        d: dict[str, Any] = {}

        async def _get_list_vault_paths() -> list[str]:
            """get the list of vault path defined in pydantic settings"""
            vault_path_list: list[str] = []
            for _fieldname, field in filter(
                lambda item: item[1].json_schema_extra,
                self.settings_cls.model_fields.items(),
            ):
                vault_path, _vault_secret_key = self._get_field_vault_metadata(
                    field_name=_fieldname, field=field
                )
                if vault_path not in vault_path_list:
                    vault_path_list.append(vault_path)

            return vault_path_list

        @concurrency_limiter(max_concurrent=5)
        async def _get_vault_secrets(
            _vault: InternalHttpVault, vault_path: str
        ) -> dict[str, SecretStr]:
            return await _vault.get_secrets(vault_path=vault_path)

        @reattempt
        async def get_secrets():
            k: dict[str, Any] = {}

            async with InternalHttpVault(
                url=vault_url,
                namespace=vault_namespace,
                auth_backend=auth_backend,
            ) as vault:
                vault_path_list: list[str] = await _get_list_vault_paths()
                vault_secrets_list: list[dict[str, SecretStr]] = await asyncio.gather(
                    *[
                        _get_vault_secrets(_vault=vault, vault_path=vault_path)
                        for vault_path in vault_path_list
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
