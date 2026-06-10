from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from pydantic import SecretStr

from pydantic2_settings_vault.features.authentication.backends import (
    AppRoleAuthBackend,
    TokenAuthBackend,
)
from pydantic2_settings_vault.shared.infrastructure import vault_http
from pydantic2_settings_vault.shared.infrastructure.vault_client_config import (
    VaultClientConfig,
)
from pydantic2_settings_vault.shared.infrastructure.vault_http import InternalHttpVault
from test.features.shared.vault_mocks import (
    mock_aiohttp_response,
    mock_vault_http_session,
)


@pytest.mark.asyncio
async def test_internal_http_vault_direct_token_auth_requires_token():
    backend = MagicMock()
    backend.uses_login = False
    backend.direct_token = None
    backend.display_name = MagicMock(return_value="token")
    vault = InternalHttpVault(
        url="http://127.0.0.1:8200",
        namespace=None,
        auth_backend=backend,
    )

    with pytest.raises(ValueError, match="Vault token auth requires a token"):
        await vault.authenticate()


@pytest.mark.asyncio
async def test_internal_http_vault_get_secrets_requires_authentication():
    backend = TokenAuthBackend(token=SecretStr("root-token"))
    vault = InternalHttpVault(
        url="http://127.0.0.1:8200",
        namespace=None,
        auth_backend=backend,
    )
    vault.token = None  # type: ignore[assignment]

    with pytest.raises(ValueError, match="Authentication is mandatory"):
        await vault.get_secrets("secret/test")


@pytest.mark.asyncio
async def test_internal_http_vault_get_secrets_http_error():
    backend = TokenAuthBackend(token=SecretStr("root-token"))
    vault = InternalHttpVault(
        url="http://127.0.0.1:8200",
        namespace="tenant-a",
        auth_backend=backend,
        default_kv_version=2,
    )
    vault.token = SecretStr("root-token")
    vault.session = mock_vault_http_session(
        get_response=mock_aiohttp_response(status=404, text="secret not found"),
    )

    with pytest.raises(ValueError, match="Failed to retrieve secret from Vault path"):
        await vault.get_secrets("secret/test")

    vault.session.get.assert_called_once_with(
        "http://127.0.0.1:8200/v1/secret/data/test",
        headers={
            "X-Vault-Token": "root-token",
            "X-Vault-Namespace": "tenant-a",
        },
    )
    vault.session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_internal_http_vault_get_secrets_network_failure():
    backend = TokenAuthBackend(token=SecretStr("root-token"))
    vault = InternalHttpVault(
        url="http://127.0.0.1:8200",
        namespace=None,
        auth_backend=backend,
    )
    vault.token = SecretStr("root-token")
    vault.session = mock_vault_http_session(
        get_side_effect=aiohttp.ClientError("connection refused"),
    )

    with pytest.raises(aiohttp.ClientError, match="connection refused"):
        await vault.get_secrets("secret/data/test")

    vault.session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_internal_http_vault_uses_custom_request_timeout(monkeypatch):
    backend = TokenAuthBackend(token=SecretStr("root-token"))
    captured_timeouts: list[float] = []
    original_client_timeout = vault_http.aiohttp.ClientTimeout

    def capture_client_timeout(*, total: float):
        captured_timeouts.append(total)
        return original_client_timeout(total=total)

    session = AsyncMock()
    session.closed = False
    session.close = AsyncMock()

    monkeypatch.setattr(
        vault_http.aiohttp,
        "ClientTimeout",
        capture_client_timeout,
    )
    monkeypatch.setattr(
        vault_http,
        "ClientSession",
        MagicMock(return_value=session),
    )

    async with InternalHttpVault(
        url="http://127.0.0.1:8200",
        namespace=None,
        auth_backend=backend,
        client_config=VaultClientConfig(request_timeout=99.0),
    ):
        pass

    assert captured_timeouts == [99.0]


@pytest.mark.asyncio
async def test_internal_http_vault_context_manager_success(monkeypatch):
    backend = TokenAuthBackend(token=SecretStr("root-token"))
    session = AsyncMock()
    session.closed = False
    session.close = AsyncMock()
    monkeypatch.setattr(
        vault_http,
        "ClientSession",
        MagicMock(return_value=session),
    )

    async with InternalHttpVault(
        url="http://127.0.0.1:8200",
        namespace=None,
        auth_backend=backend,
    ) as vault:
        assert vault.token.get_secret_value() == "root-token"
        assert vault.session is session

    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_internal_http_vault_context_manager_auth_failure_closes_session(
    monkeypatch,
):
    backend = AppRoleAuthBackend(
        role_id=SecretStr("role-id"),
        secret_id=SecretStr("secret-id"),
    )
    session = AsyncMock()
    session.closed = False
    session.close = AsyncMock()
    session.post = MagicMock(
        return_value=mock_aiohttp_response(status=403, text="permission denied"),
    )

    monkeypatch.setattr(
        vault_http,
        "ClientSession",
        MagicMock(return_value=session),
    )

    with pytest.raises(ValueError, match="Failed to authenticate with Vault approle"):
        async with InternalHttpVault(
            url="http://127.0.0.1:8200",
            namespace=None,
            auth_backend=backend,
        ):
            pass

    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_internal_http_vault_context_manager_exit_closes_open_session(
    monkeypatch,
):
    backend = TokenAuthBackend(token=SecretStr("root-token"))
    session = AsyncMock()
    session.closed = False
    session.close = AsyncMock()

    monkeypatch.setattr(
        vault_http,
        "ClientSession",
        MagicMock(return_value=session),
    )

    vault = InternalHttpVault(
        url="http://127.0.0.1:8200",
        namespace=None,
        auth_backend=backend,
    )
    await vault.__aenter__()
    await vault.__aexit__(None, None, None)

    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_internal_http_vault_context_manager_exit_skips_closed_session(
    monkeypatch,
):
    backend = TokenAuthBackend(token=SecretStr("root-token"))
    session = AsyncMock()
    session.closed = True
    session.close = AsyncMock()
    monkeypatch.setattr(
        vault_http,
        "ClientSession",
        MagicMock(return_value=session),
    )

    vault = InternalHttpVault(
        url="http://127.0.0.1:8200",
        namespace=None,
        auth_backend=backend,
    )
    await vault.__aenter__()
    await vault.__aexit__(None, None, None)

    session.close.assert_not_called()
