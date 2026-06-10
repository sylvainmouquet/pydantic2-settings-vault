import pytest

from pydantic2_settings_vault.shared.infrastructure.vault_client_config import (
    VaultClientConfig,
)


def test_vault_client_config_defaults():
    config = VaultClientConfig()

    assert config.request_timeout == 30.0
    assert config.max_concurrent_requests == 5
    assert config.retry_max_attempts == 5
    assert config.retry_min_delay == 0.1
    assert config.retry_max_delay == 0.2


@pytest.mark.parametrize(
    ("factory_name", "expected_timeout", "expected_concurrency", "expected_retries"),
    [
        ("for_local", 60.0, 3, 3),
        ("for_ci", 15.0, 5, 2),
        ("for_production", 30.0, 10, 5),
    ],
)
def test_vault_client_config_presets(
    factory_name,
    expected_timeout,
    expected_concurrency,
    expected_retries,
):
    config = getattr(VaultClientConfig, factory_name)()

    assert config.request_timeout == expected_timeout
    assert config.max_concurrent_requests == expected_concurrency
    assert config.retry_max_attempts == expected_retries


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"request_timeout": 0}, "request_timeout"),
        ({"max_concurrent_requests": 0}, "max_concurrent_requests"),
        ({"retry_max_attempts": -1}, "retry_max_attempts"),
        ({"retry_min_delay": -0.1}, "retry_min_delay"),
        ({"retry_max_delay": -0.1}, "retry_max_delay"),
        (
            {"retry_min_delay": 1.0, "retry_max_delay": 0.5},
            "retry_min_delay must be less than or equal to retry_max_delay",
        ),
    ],
)
def test_vault_client_config_rejects_invalid_values(kwargs, match):
    with pytest.raises(ValueError, match=match):
        VaultClientConfig(**kwargs)
