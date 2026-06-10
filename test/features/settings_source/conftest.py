import os

import pytest

SHOW_EXCEPTIONS = False


def parse_vault_credentials(credentials: str) -> dict[str, str]:
    return dict(
        line.split("=", maxsplit=1)
        for line in credentials.splitlines()
        if "=" in line
    )


def configure_vault_env(vault_container, credentials_dict: dict[str, str]) -> None:
    os.environ["VAULT_ROLE_ID"] = credentials_dict["ROLE_ID"]
    os.environ["VAULT_SECRET_ID"] = credentials_dict["SECRET_ID"]
    os.environ["VAULT_URL"] = f"http://{vault_container.host}:{vault_container.port}"


@pytest.fixture
def disable_logging_exception(mocker):
    if not SHOW_EXCEPTIONS:
        mocker.patch("logging.exception", lambda *args, **kwargs: None)
