from typing import Any


def normalize_creds_path(vault_path: str) -> str:
    """Return the Vault HTTP API path for a logical database secret path."""
    if "/" not in vault_path:
        return vault_path

    mount_point, secret_path = vault_path.split("/", maxsplit=1)
    if not secret_path:
        return vault_path

    if secret_path.startswith("data/"):
        return f"{mount_point}/{secret_path[5:]}"
    return vault_path


def extract_creds_secret_data(response_json: dict[str, Any]) -> dict[str, Any]:
    """Extract the key/value map from a Vault database read response."""
    data = response_json.get("data")
    if not isinstance(data, dict):
        raise ValueError("Vault response missing 'data' field")

    return data
