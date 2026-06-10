from http import HTTPStatus
import ssl

import aiohttp
from aiohttp import ClientSession
import certifi
from pydantic import SecretStr

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
                        "Failed to authenticate with Vault AppRole. "
                        f"Error code: {response.status}. Error message: {error_msg}"
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
                        f"Failed to retrieve secret from Vault path '{vault_path}'. "
                        f"Error code: {response.status}. Error message: {error_msg}"
                    )
        except Exception as e:
            await self.session.close()
            raise e
