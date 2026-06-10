from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from pydantic import SecretStr


def mock_aiohttp_response(
    *,
    status: int,
    json_data: dict[str, Any] | None = None,
    text: str = "",
) -> AsyncMock:
    """Build an async context manager mock for an aiohttp ClientResponse."""
    response = AsyncMock()
    response.status = status
    response.json = AsyncMock(return_value=json_data or {})
    response.text = AsyncMock(return_value=text)
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    return response


def mock_vault_http_session(
    *,
    post_response: AsyncMock | None = None,
    get_response: AsyncMock | None = None,
    get_side_effect: Callable[..., Any] | BaseException | None = None,
) -> MagicMock:
    """Build a mock aiohttp ClientSession for Vault HTTP tests."""
    session = MagicMock()
    if post_response is not None:
        session.post = MagicMock(return_value=post_response)
    if get_response is not None:
        session.get = MagicMock(return_value=get_response)
    if get_side_effect is not None:
        session.get = MagicMock(side_effect=get_side_effect)
    session.closed = False
    session.close = AsyncMock()
    return session


def patch_internal_http_vault(
    mocker,
    *,
    secrets: dict[str, SecretStr] | None = None,
    get_secrets_side_effect: BaseException | None = None,
    enter_side_effect: BaseException | None = None,
) -> AsyncMock:
    """Patch InternalHttpVault in the settings source module with a controllable mock."""
    vault_instance = AsyncMock()
    if get_secrets_side_effect is not None:
        vault_instance.get_secrets = AsyncMock(side_effect=get_secrets_side_effect)
    else:
        vault_instance.get_secrets = AsyncMock(return_value=secrets or {})

    if enter_side_effect is not None:
        vault_instance.__aenter__ = AsyncMock(side_effect=enter_side_effect)
    else:
        vault_instance.__aenter__ = AsyncMock(return_value=vault_instance)
    vault_instance.__aexit__ = AsyncMock(return_value=False)

    mocker.patch(
        "pydantic2_settings_vault.features.settings_source.source.InternalHttpVault",
        return_value=vault_instance,
    )
    return vault_instance
