import os
from typing import Any, Literal, cast

KVVersion = Literal[1, 2]
VAULT_KV_VERSION_ENV_VAR = "VAULT_KV_VERSION"
VAULT_KV_VERSION_METADATA_KEY = "vault_kv_version"
SUPPORTED_KV_VERSIONS: frozenset[int] = frozenset({1, 2})


def _validate_kv_version(kv_version: int) -> KVVersion:
    if kv_version not in SUPPORTED_KV_VERSIONS:
        supported_versions = ", ".join(
            str(version) for version in sorted(SUPPORTED_KV_VERSIONS)
        )
        raise ValueError(
            f"Unsupported Vault KV version {kv_version!r}. "
            f"Supported versions: {supported_versions}."
        )
    return cast(KVVersion, kv_version)


def resolve_kv_version_from_env() -> KVVersion:
    raw_version = os.getenv(VAULT_KV_VERSION_ENV_VAR, "2")
    try:
        parsed_version = int(raw_version)
    except ValueError:
        raise ValueError(
            f"Invalid {VAULT_KV_VERSION_ENV_VAR} value {raw_version!r}. "
            "Expected 1 or 2."
        ) from None

    return _validate_kv_version(parsed_version)


def resolve_kv_version(
    field_metadata: dict[str, Any] | None = None,
    *,
    default: int | None = None,
) -> KVVersion:
    if field_metadata and field_metadata.get(VAULT_KV_VERSION_METADATA_KEY) is not None:
        raw_version = field_metadata[VAULT_KV_VERSION_METADATA_KEY]
        try:
            parsed_version = int(raw_version)
        except (TypeError, ValueError):
            raise ValueError(
                f"Invalid field metadata {VAULT_KV_VERSION_METADATA_KEY} value "
                f"{raw_version!r}. Expected 1 or 2."
            ) from None
        return _validate_kv_version(parsed_version)

    if default is not None:
        return _validate_kv_version(default)

    return resolve_kv_version_from_env()


def normalize_kv_path(vault_path: str, kv_version: int) -> str:
    """Return the Vault HTTP API path for a logical KV secret path."""
    validated_version = _validate_kv_version(kv_version)
    if "/" not in vault_path:
        return vault_path

    mount_point, secret_path = vault_path.split("/", maxsplit=1)
    if not secret_path:
        return vault_path

    if validated_version == 2:
        if secret_path.startswith("data/"):
            return vault_path
        return f"{mount_point}/data/{secret_path}"

    if secret_path.startswith("data/"):
        return f"{mount_point}/{secret_path[5:]}"
    return vault_path


def extract_kv_secret_data(
    response_json: dict[str, Any], kv_version: int
) -> dict[str, Any]:
    """Extract the key/value map from a Vault KV read response."""
    validated_version = _validate_kv_version(kv_version)
    data = response_json.get("data")
    if not isinstance(data, dict):
        raise ValueError("Vault response missing 'data' field")

    if validated_version == 2:
        secret_data = data.get("data")
        if not isinstance(secret_data, dict):
            raise ValueError("Vault KV v2 response missing 'data.data' field")
        return secret_data

    return data
