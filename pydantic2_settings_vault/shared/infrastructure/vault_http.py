from http import HTTPStatus
import ssl

import aiohttp
from aiohttp import ClientSession
import certifi
from pydantic import SecretStr

from pydantic2_settings_vault.features.authentication.backends import VaultAuthBackend

CONST_HEADER_X_VAULT_TOKEN: str = "X-Vault-Token"
CONST_HEADER_X_VAULT_NAMESPACE: str = "X-Vault-Namespace"

ssl_context = ssl.create_default_context(cafile=certifi.where())


class InternalHttpVault:
    token: SecretStr
    session: ClientSession

    def __init__(
        self,
        url: str,
        namespace: str | None,
        auth_backend: VaultAuthBackend,
    ):
        self.url = url
        self.namespace = namespace
        self.auth_backend = auth_backend

    def _build_namespace_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.namespace:
            headers[CONST_HEADER_X_VAULT_NAMESPACE] = self.namespace
        return headers

    async def authenticate(self) -> None:
        if not self.auth_backend.uses_login:
            direct_token = self.auth_backend.direct_token
            if direct_token is None:
                raise ValueError(
                    f"Vault {self.auth_backend.display_name()} auth requires a token."
                )
            self.token = direct_token
            return

        headers = self._build_namespace_headers()
        login_url = f"{self.url}/v1/{self.auth_backend.login_path}"
        login_payload = self.auth_backend.build_login_payload()
        client_ssl = self.auth_backend.client_ssl_for_login

        if client_ssl is not None:
            connector = aiohttp.TCPConnector(limit=1, ssl=client_ssl)
            timeout = aiohttp.ClientTimeout(total=30)
            async with ClientSession(connector=connector, timeout=timeout) as login_session:
                await self._perform_login(
                    login_session,
                    login_url,
                    login_payload,
                    headers,
                )
            return

        await self._perform_login(
            self.session,
            login_url,
            login_payload,
            headers,
        )

    async def _perform_login(
        self,
        session: ClientSession,
        login_url: str,
        login_payload: dict,
        headers: dict[str, str],
    ) -> None:
        async with session.post(
            login_url,
            json=login_payload,
            headers=headers,
        ) as response:
            if response.status == HTTPStatus.OK:
                response_data = await response.json()
                self.token = SecretStr(response_data["auth"]["client_token"])
                return

            error_msg = await response.text()
            raise ValueError(
                f"Failed to authenticate with Vault {self.auth_backend.display_name()}. "
                f"Error code: {response.status}. Error message: {error_msg}"
            )

    async def __aenter__(self):
        connector = aiohttp.TCPConnector(limit=10, ssl=ssl_context)
        timeout = aiohttp.ClientTimeout(total=30)
        self.session = ClientSession(connector=connector, timeout=timeout)

        try:
            await self.authenticate()
        except Exception as exc:
            await self.session.close()
            raise exc

        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.session and not self.session.closed:
            await self.session.close()

    async def get_secrets(self, vault_path: str) -> dict[str, SecretStr]:
        if not self.token:
            raise ValueError("Authentication is mandatory")

        try:
            headers = {
                CONST_HEADER_X_VAULT_TOKEN: self.token.get_secret_value(),
                **self._build_namespace_headers(),
            }
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

                error_msg = await response.text()
                raise ValueError(
                    f"Failed to retrieve secret from Vault path '{vault_path}'. "
                    f"Error code: {response.status}. Error message: {error_msg}"
                )
        except Exception as exc:
            await self.session.close()
            raise exc
