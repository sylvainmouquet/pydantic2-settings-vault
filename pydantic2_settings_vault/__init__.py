__version__ = "1.0.1"
__all__ = ("__version__", "VaultConfigSettingsSource")

import asyncio
import logging
import concurrent.futures
import os
from typing import Any, Tuple

from concurrency_limiter import concurrency_limiter
from pydantic import SecretStr
from pydantic.fields import FieldInfo
from pydantic_settings import (
    PydanticBaseSettingsSource,
)

from http import HTTPStatus

import aiohttp
from aiohttp import ClientSession


from reattempt import reattempt
import certifi
import ssl

logger = logging.getLogger("pydantic2-settings-vault")
logger.addHandler(logging.NullHandler())

CONST_HEADER_X_VAULT_TOKEN: str = "X-Vault-Token"
CONST_HEADER_X_VAULT_NAMESPACE: str = "X-Vault-Namespace"

ssl_context = ssl.create_default_context(cafile=certifi.where())


class InternalHttpVault:
    token: SecretStr
    session: ClientSession

    def __init__(
        self, url: str, namespace: str | None, role_id: SecretStr, secret_id: SecretStr
    ):
        self.url = url
        self.namespace = namespace
        self.role_id = role_id
        self.secret_id = secret_id

    async def __aenter__(self):
        connector = aiohttp.TCPConnector(limit=10, ssl=ssl_context)
        timeout = aiohttp.ClientTimeout(total=30)
        self.session = ClientSession(connector=connector, timeout=timeout)

        data = {
            "role_id": self.role_id.get_secret_value(),
            "secret_id": self.secret_id.get_secret_value(),
        }
        try:
            headers = {}
            if self.namespace:
                headers[CONST_HEADER_X_VAULT_NAMESPACE] = self.namespace
            async with self.session.post(
                f"{self.url}/v1/auth/approle/login", json=data, headers=headers
            ) as response:
                if response.status == HTTPStatus.OK:
                    response_data = await response.json()
                    self.token = SecretStr(response_data["auth"]["client_token"])
                else:
                    error_msg = await response.text()
                    raise ValueError(
                        f"Failed to authenticate. Error code: {response.status}. Error message: {error_msg}"
                    )
        except Exception as e:
            await self.session.close()
            raise e

        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.session and not self.session.closed:
            await self.session.close()

    async def get_secrets(self, vault_path: str) -> dict[str, SecretStr]:
        if not self.token:
            raise ValueError("Authentication is mandatory")

        try:
            headers = {CONST_HEADER_X_VAULT_TOKEN: self.token.get_secret_value()}
            if self.namespace:
                headers[CONST_HEADER_X_VAULT_NAMESPACE] = self.namespace
            async with self.session.get(
                f"{self.url}/v1/{vault_path}",
                headers=headers,
            ) as response:
                if response.status == HTTPStatus.OK:
                    secrets = await response.json()
                    result = {
                        key: SecretStr(value)
                        for key, value in secrets["data"]["data"].items()
                    }
                    return result
                else:
                    error_msg = await response.text()
                    raise ValueError(
                        f"Failed to retrieve secret. Error code: {response.status}. Error message: {error_msg}"
                    )
        except Exception as e:
            await self.session.close()
            raise e


class VaultConfigSettingsSource(PydanticBaseSettingsSource):
    CONST_HEADER_X_VAULT_TOKEN: str = "X-Vault-Token"

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
        vault_role_id: SecretStr = SecretStr(os.getenv("VAULT_ROLE_ID"))
        vault_secret_id: SecretStr = SecretStr(os.getenv("VAULT_SECRET_ID"))

        if (
            not vault_role_id.get_secret_value()
            or not vault_secret_id.get_secret_value()
        ):
            raise ValueError("VAULT_ROLE_ID and VAULT_SECRET_ID are mandatory")

        d: dict[str, Any] = {}

        async def _get_list_vault_paths() -> list[str]:
            """get the list of vault path defined in pydantic settings"""
            vault_path_list: list[str] = []
            for _fieldname, field in filter(
                lambda item: item[1].json_schema_extra,
                self.settings_cls.model_fields.items(),
            ):
                vault_path: str = field.json_schema_extra["vault_secret_path"]  # type: ignore
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
                role_id=vault_role_id,
                secret_id=vault_secret_id,
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
                vault_secret_key: str = field.json_schema_extra["vault_secret_key"]  # type: ignore

                if vault_secret_key in vault_secrets_dict:
                    k[field_name] = vault_secrets_dict[
                        vault_secret_key
                    ].get_secret_value()
                else:
                    logger.error(f"Key {vault_secret_key} not found in the Vault")
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
