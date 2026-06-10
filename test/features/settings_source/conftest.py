import os

import pytest
from reattempt import reattempt

SHOW_EXCEPTIONS = False


def parse_vault_credentials(credentials: str) -> dict[str, str]:
    return dict(
        line.split("=", maxsplit=1) for line in credentials.splitlines() if "=" in line
    )


@reattempt(max_retries=30, min_time=0.2, max_time=1.0)
def fetch_vault_credentials(vault_container) -> dict[str, str]:
    """Return AppRole credentials once the Vault test container is initialized."""
    try:
        credentials_dict = parse_vault_credentials(
            vault_container.execute(["cat", "/vault-credentials.env"])
        )
        if credentials_dict.get("ROLE_ID") and credentials_dict.get("SECRET_ID"):
            return credentials_dict
    except Exception:
        pass

    role_id = vault_container.execute(
        ["vault", "read", "-field=role_id", "auth/approle/role/my-app-role/role-id"]
    ).strip()
    secret_id = vault_container.execute(
        [
            "vault",
            "write",
            "-field=secret_id",
            "-f",
            "auth/approle/role/my-app-role/secret-id",
        ]
    ).strip()
    if not role_id or not secret_id:
        raise RuntimeError("Vault AppRole credentials are not available yet")
    return {"ROLE_ID": role_id, "SECRET_ID": secret_id}


def configure_vault_env(vault_container, credentials_dict: dict[str, str]) -> None:
    os.environ["VAULT_AUTH_METHOD"] = "approle"
    os.environ["VAULT_ROLE_ID"] = credentials_dict["ROLE_ID"]
    os.environ["VAULT_SECRET_ID"] = credentials_dict["SECRET_ID"]
    os.environ["VAULT_URL"] = f"http://{vault_container.host}:{vault_container.port}"


VAULT_DEV_ROOT_TOKEN = "00000000-0000-0000-0000-000000000000"


def configure_vault_token_env(
    vault_container, credentials_dict: dict[str, str]
) -> None:
    os.environ["VAULT_AUTH_METHOD"] = "token"
    os.environ["VAULT_TOKEN"] = credentials_dict.get("ROOT_TOKEN", VAULT_DEV_ROOT_TOKEN)
    os.environ["VAULT_URL"] = f"http://{vault_container.host}:{vault_container.port}"
    os.environ.pop("VAULT_ROLE_ID", None)
    os.environ.pop("VAULT_SECRET_ID", None)


@pytest.fixture
def disable_logging_exception(mocker):
    if not SHOW_EXCEPTIONS:
        mocker.patch("logging.exception", lambda *args, **kwargs: None)
