from pydantic import SecretStr

from pydantic2_settings_vault.features.settings_source.source import (
    VaultConfigSettingsSource,
)
from pydantic2_settings_vault.shared.infrastructure.vault_client_config import (
    VaultClientConfig,
)
from test.features.settings_source.settings import ValidAppSettings
from test.features.shared.vault_mocks import patch_internal_http_vault


def configure_token_auth(monkeypatch) -> None:
    monkeypatch.setenv("VAULT_AUTH_METHOD", "token")
    monkeypatch.setenv("VAULT_TOKEN", "root-token")
    monkeypatch.delenv("VAULT_ROLE_ID", raising=False)
    monkeypatch.delenv("VAULT_SECRET_ID", raising=False)
    monkeypatch.delenv("VAULT_KV_VERSION", raising=False)


def test_source_passes_client_config_to_internal_http_vault(mocker, monkeypatch):
    configure_token_auth(monkeypatch)
    client_config = VaultClientConfig(
        request_timeout=42.0,
        max_concurrent_requests=2,
        retry_max_attempts=1,
        retry_min_delay=0.05,
        retry_max_delay=0.1,
    )
    vault_class = mocker.patch(
        "pydantic2_settings_vault.features.settings_source.source.InternalHttpVault",
        autospec=True,
    )
    vault_instance = vault_class.return_value
    vault_instance.__aenter__ = mocker.AsyncMock(return_value=vault_instance)
    vault_instance.__aexit__ = mocker.AsyncMock(return_value=False)
    vault_instance.get_secrets = mocker.AsyncMock(
        return_value={"FOO": SecretStr("BAR")},
    )

    source = VaultConfigSettingsSource(
        settings_cls=ValidAppSettings,
        client_config=client_config,
    )
    result = source()

    assert result == {"FOO": "BAR"}
    vault_class.assert_called_once_with(
        url="http://127.0.0.1:8200",
        namespace=None,
        auth_backend=mocker.ANY,
        default_kv_version=2,
        client_config=client_config,
    )


def test_source_uses_configured_concurrency_limiter(mocker, monkeypatch):
    configure_token_auth(monkeypatch)
    captured: dict[str, int] = {}

    def capture_limiter(max_concurrent: int):
        captured["max_concurrent"] = max_concurrent

        def decorator(func):
            return func

        return decorator

    mocker.patch(
        "pydantic2_settings_vault.features.settings_source.source.concurrency_limiter",
        side_effect=capture_limiter,
    )
    patch_internal_http_vault(mocker, secrets={"FOO": SecretStr("BAR")})

    source = VaultConfigSettingsSource(
        settings_cls=ValidAppSettings,
        client_config=VaultClientConfig(max_concurrent_requests=7),
    )
    source()

    assert captured["max_concurrent"] == 7


def test_source_uses_configured_retry_settings(mocker, monkeypatch):
    configure_token_auth(monkeypatch)
    captured: dict[str, float | int] = {}

    def capture_reattempt(**kwargs):
        captured.update(kwargs)

        def decorator(func):
            return func

        return decorator

    mocker.patch(
        "pydantic2_settings_vault.features.settings_source.source.reattempt",
        side_effect=capture_reattempt,
    )
    patch_internal_http_vault(mocker, secrets={"FOO": SecretStr("BAR")})

    source = VaultConfigSettingsSource(
        settings_cls=ValidAppSettings,
        client_config=VaultClientConfig(
            retry_max_attempts=2,
            retry_min_delay=0.25,
            retry_max_delay=0.75,
        ),
    )
    source()

    assert captured == {
        "max_retries": 2,
        "min_time": 0.25,
        "max_time": 0.75,
    }


