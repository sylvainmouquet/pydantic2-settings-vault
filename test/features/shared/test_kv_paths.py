import pytest

from pydantic2_settings_vault.shared.infrastructure.kv_paths import (
    extract_kv_secret_data,
    normalize_kv_path,
    resolve_kv_version,
    resolve_kv_version_from_env,
)


def test_normalize_kv_path_v2_inserts_data_segment():
    assert normalize_kv_path("secret/test", 2) == "secret/data/test"


def test_normalize_kv_path_v2_preserves_existing_data_segment():
    assert normalize_kv_path("secret/data/test", 2) == "secret/data/test"


def test_normalize_kv_path_v1_strips_data_segment():
    assert normalize_kv_path("secret/data/test", 1) == "secret/test"


def test_normalize_kv_path_v1_preserves_logical_path():
    assert normalize_kv_path("secret/test", 1) == "secret/test"


def test_extract_kv_secret_data_v2():
    response = {"data": {"data": {"FOO": "BAR"}, "metadata": {"version": 1}}}
    assert extract_kv_secret_data(response, 2) == {"FOO": "BAR"}


def test_extract_kv_secret_data_v1():
    response = {"data": {"FOO": "BAR"}}
    assert extract_kv_secret_data(response, 1) == {"FOO": "BAR"}


def test_resolve_kv_version_from_env_default(monkeypatch):
    monkeypatch.delenv("VAULT_KV_VERSION", raising=False)
    assert resolve_kv_version_from_env() == 2


def test_resolve_kv_version_from_env_override(monkeypatch):
    monkeypatch.setenv("VAULT_KV_VERSION", "1")
    assert resolve_kv_version_from_env() == 1


def test_resolve_kv_version_from_env_invalid(monkeypatch):
    monkeypatch.setenv("VAULT_KV_VERSION", "3")
    with pytest.raises(ValueError, match="Unsupported Vault KV version"):
        resolve_kv_version_from_env()


def test_resolve_kv_version_field_override():
    assert resolve_kv_version({"vault_kv_version": 1}, default=2) == 1


def test_resolve_kv_version_invalid_field_metadata():
    with pytest.raises(ValueError, match="vault_kv_version"):
        resolve_kv_version({"vault_kv_version": "bad"})


def test_resolve_kv_version_uses_explicit_default():
    assert resolve_kv_version(None, default=1) == 1


def test_resolve_kv_version_from_env_non_integer(monkeypatch):
    monkeypatch.setenv("VAULT_KV_VERSION", "v2")
    with pytest.raises(ValueError, match="Invalid VAULT_KV_VERSION"):
        resolve_kv_version_from_env()


def test_normalize_kv_path_without_slash():
    assert normalize_kv_path("secret", 2) == "secret"


def test_normalize_kv_path_empty_secret_segment():
    assert normalize_kv_path("secret/", 2) == "secret/"


def test_extract_kv_secret_data_missing_data():
    with pytest.raises(ValueError, match="missing 'data' field"):
        extract_kv_secret_data({}, 1)


def test_extract_kv_secret_data_v2_missing_nested_data():
    with pytest.raises(ValueError, match="data.data"):
        extract_kv_secret_data({"data": {"metadata": {"version": 1}}}, 2)
