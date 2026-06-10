import base64
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import SecretStr

from pydantic2_settings_vault.features.authentication.backends import (
    AppRoleAuthBackend,
    AwsAuthBackend,
    AzureAuthBackend,
    GcpAuthBackend,
    KubernetesAuthBackend,
    TokenAuthBackend,
)
from pydantic2_settings_vault.features.authentication.registry import (
    get_auth_backend_from_env,
    get_required_env_vars_for_method,
    resolve_auth_method,
)
from pydantic2_settings_vault.shared.infrastructure.vault_http import InternalHttpVault


def test_token_auth_backend_skips_login():
    backend = TokenAuthBackend(token=SecretStr("root-token"))

    assert backend.uses_login is False
    assert backend.direct_token.get_secret_value() == "root-token"
    assert backend.login_path == "auth/token/login"


def test_approle_auth_backend_builds_payload():
    backend = AppRoleAuthBackend(
        role_id=SecretStr("role-id"),
        secret_id=SecretStr("secret-id"),
    )

    assert backend.build_login_payload() == {
        "role_id": "role-id",
        "secret_id": "secret-id",
    }
    assert backend.login_path == "auth/approle/login"


def test_kubernetes_auth_backend_builds_payload():
    backend = KubernetesAuthBackend(
        role="demo",
        jwt=SecretStr("jwt-token"),
        mount="custom-k8s",
    )

    assert backend.build_login_payload() == {
        "role": "demo",
        "jwt": "jwt-token",
    }
    assert backend.login_path == "auth/custom-k8s/login"


def test_kubernetes_auth_backend_reads_jwt_from_file(tmp_path, monkeypatch):
    jwt_file = tmp_path / "token"
    jwt_file.write_text("service-account-jwt\n", encoding="utf-8")
    monkeypatch.setenv("VAULT_K8S_JWT_PATH", str(jwt_file))

    jwt = KubernetesAuthBackend.resolve_jwt()

    assert jwt.get_secret_value() == "service-account-jwt"


def test_kubernetes_auth_backend_prefers_env_jwt(monkeypatch):
    monkeypatch.setenv("VAULT_K8S_JWT", "inline-jwt")

    jwt = KubernetesAuthBackend.resolve_jwt()

    assert jwt.get_secret_value() == "inline-jwt"


def test_aws_auth_backend_uses_pre_signed_payload(monkeypatch):
    monkeypatch.setenv("VAULT_AWS_IAM_REQUEST_URL", "url")
    monkeypatch.setenv("VAULT_AWS_IAM_REQUEST_BODY", "body")
    monkeypatch.setenv("VAULT_AWS_IAM_REQUEST_HEADERS", "headers")

    payload = AwsAuthBackend.resolve_login_payload("demo-role")

    assert payload == {
        "role": "demo-role",
        "iam_http_request_method": "POST",
        "iam_request_url": "url",
        "iam_request_body": "body",
        "iam_request_headers": "headers",
    }


def test_aws_auth_backend_generates_signed_payload(monkeypatch):
    monkeypatch.delenv("VAULT_AWS_IAM_REQUEST_URL", raising=False)
    monkeypatch.delenv("VAULT_AWS_IAM_REQUEST_BODY", raising=False)
    monkeypatch.delenv("VAULT_AWS_IAM_REQUEST_HEADERS", raising=False)
    monkeypatch.setenv("VAULT_AWS_IAM_SERVER_ID", "vault.example.com")

    botocore = pytest.importorskip("botocore")
    session = botocore.session.get_session()
    client = session.create_client("sts")
    endpoint = client._endpoint
    operation_model = client._service_model.operation_model("GetCallerIdentity")
    request_dict = client._convert_to_request_dict({}, operation_model)
    request_dict["headers"]["X-Vault-AWS-IAM-Server-ID"] = "vault.example.com"
    request = endpoint.create_request(request_dict, operation_model)

    payload = AwsAuthBackend.generate_iam_login_payload(
        "demo-role",
        iam_server_id="vault.example.com",
    )

    assert payload["role"] == "demo-role"
    assert payload["iam_http_request_method"] == request.method
    assert base64.b64decode(payload["iam_request_url"]).decode() == request.url
    assert base64.b64decode(payload["iam_request_body"]).decode() == (
        request.body or ""
    )
    headers = json.loads(base64.b64decode(payload["iam_request_headers"]).decode())
    assert headers["X-Vault-AWS-IAM-Server-ID"] == ["vault.example.com"]


def test_gcp_auth_backend_builds_payload():
    backend = GcpAuthBackend(role="demo", jwt=SecretStr("gcp-jwt"))

    assert backend.build_login_payload() == {
        "role": "demo",
        "jwt": "gcp-jwt",
    }


def test_gcp_auth_backend_prefers_env_jwt(monkeypatch):
    monkeypatch.setenv("VAULT_GCP_JWT", "inline-gcp-jwt")

    jwt = GcpAuthBackend.resolve_jwt("demo")

    assert jwt.get_secret_value() == "inline-gcp-jwt"


def test_azure_auth_backend_builds_payload():
    backend = AzureAuthBackend(role="demo", jwt=SecretStr("azure-jwt"))

    assert backend.build_login_payload() == {
        "role": "demo",
        "jwt": "azure-jwt",
    }


def test_azure_auth_backend_prefers_env_jwt(monkeypatch):
    monkeypatch.setenv("VAULT_AZURE_JWT", "inline-azure-jwt")

    jwt = AzureAuthBackend.resolve_jwt()

    assert jwt.get_secret_value() == "inline-azure-jwt"


def test_get_required_env_vars_for_approle():
    assert get_required_env_vars_for_method("approle") == (
        "VAULT_ROLE_ID",
        "VAULT_SECRET_ID",
    )


def test_get_required_env_vars_for_token():
    assert get_required_env_vars_for_method("token") == ("VAULT_TOKEN",)


def test_get_required_env_vars_for_kubernetes():
    assert get_required_env_vars_for_method("kubernetes") == ("VAULT_K8S_ROLE",)


def test_get_required_env_vars_for_unsupported_method():
    with pytest.raises(ValueError, match="Unsupported Vault auth method"):
        get_required_env_vars_for_method("unknown")


def test_get_auth_backend_from_env_defaults_to_approle(monkeypatch):
    monkeypatch.delenv("VAULT_AUTH_METHOD", raising=False)
    monkeypatch.setenv("VAULT_ROLE_ID", "role-id")
    monkeypatch.setenv("VAULT_SECRET_ID", "secret-id")

    backend = get_auth_backend_from_env()

    assert isinstance(backend, AppRoleAuthBackend)
    assert resolve_auth_method() == "approle"


def test_get_auth_backend_from_env_token(monkeypatch):
    monkeypatch.setenv("VAULT_AUTH_METHOD", "token")
    monkeypatch.setenv("VAULT_TOKEN", "root-token")

    backend = get_auth_backend_from_env()

    assert isinstance(backend, TokenAuthBackend)
    assert backend.direct_token.get_secret_value() == "root-token"


def test_get_auth_backend_from_env_custom_mount(monkeypatch):
    monkeypatch.setenv("VAULT_AUTH_METHOD", "token")
    monkeypatch.setenv("VAULT_TOKEN", "root-token")
    monkeypatch.setenv("VAULT_AUTH_MOUNT", "custom-token")

    backend = get_auth_backend_from_env()

    assert backend.login_path == "auth/custom-token/login"


@pytest.mark.asyncio
async def test_internal_http_vault_token_auth_skips_login():
    backend = TokenAuthBackend(token=SecretStr("root-token"))
    vault = InternalHttpVault(
        url="http://127.0.0.1:8200",
        namespace=None,
        auth_backend=backend,
    )

    vault.session = AsyncMock()
    vault.session.closed = False

    await vault.authenticate()

    vault.session.post.assert_not_called()
    assert vault.token.get_secret_value() == "root-token"


@pytest.mark.asyncio
async def test_internal_http_vault_approle_login():
    backend = AppRoleAuthBackend(
        role_id=SecretStr("role-id"),
        secret_id=SecretStr("secret-id"),
    )
    vault = InternalHttpVault(
        url="http://127.0.0.1:8200",
        namespace="tenant-a",
        auth_backend=backend,
    )

    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"auth": {"client_token": "vault-token"}})
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)

    vault.session = MagicMock()
    vault.session.post = MagicMock(return_value=response)

    await vault.authenticate()

    vault.session.post.assert_called_once_with(
        "http://127.0.0.1:8200/v1/auth/approle/login",
        json={"role_id": "role-id", "secret_id": "secret-id"},
        headers={"X-Vault-Namespace": "tenant-a"},
    )
    assert vault.token.get_secret_value() == "vault-token"


@pytest.mark.asyncio
async def test_internal_http_vault_login_failure():
    backend = AppRoleAuthBackend(
        role_id=SecretStr("role-id"),
        secret_id=SecretStr("secret-id"),
    )
    vault = InternalHttpVault(
        url="http://127.0.0.1:8200",
        namespace=None,
        auth_backend=backend,
    )

    response = AsyncMock()
    response.status = 403
    response.text = AsyncMock(return_value="permission denied")
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)

    vault.session = MagicMock()
    vault.session.post = MagicMock(return_value=response)

    with pytest.raises(ValueError, match="Failed to authenticate with Vault approle"):
        await vault.authenticate()
