import base64
import json
import ssl
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from pydantic import SecretStr

from pydantic2_settings_vault.features.authentication.backends import (
    AlicloudAuthBackend,
    AppRoleAuthBackend,
    AwsAuthBackend,
    AzureAuthBackend,
    CertAuthBackend,
    CfAuthBackend,
    GcpAuthBackend,
    GithubAuthBackend,
    JwtAuthBackend,
    KerberosAuthBackend,
    KubernetesAuthBackend,
    LdapAuthBackend,
    OciAuthBackend,
    OidcAuthBackend,
    OktaAuthBackend,
    PcfAuthBackend,
    RadiusAuthBackend,
    TokenAuthBackend,
    UserpassAuthBackend,
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
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")

    pytest.importorskip("botocore")
    import botocore.session

    session = botocore.session.get_session()
    client = session.create_client("sts")
    endpoint = client._endpoint
    operation_model = client._service_model.operation_model("GetCallerIdentity")
    request_dict = client._convert_to_request_dict(
        {},
        operation_model,
        client.meta.endpoint_url,
    )
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


@pytest.mark.asyncio
async def test_internal_http_vault_get_secrets_kv_v2():
    backend = TokenAuthBackend(token=SecretStr("root-token"))
    vault = InternalHttpVault(
        url="http://127.0.0.1:8200",
        namespace=None,
        auth_backend=backend,
        default_kv_version=2,
    )
    vault.token = SecretStr("root-token")

    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(
        return_value={"data": {"data": {"FOO": "BAR"}, "metadata": {"version": 1}}}
    )
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)

    vault.session = MagicMock()
    vault.session.get = MagicMock(return_value=response)

    secrets = await vault.get_secrets("secret/test", kv_version=2)

    vault.session.get.assert_called_once_with(
        "http://127.0.0.1:8200/v1/secret/data/test",
        headers={"X-Vault-Token": "root-token"},
    )
    assert secrets["FOO"].get_secret_value() == "BAR"


@pytest.mark.asyncio
async def test_internal_http_vault_get_secrets_kv_v1():
    backend = TokenAuthBackend(token=SecretStr("root-token"))
    vault = InternalHttpVault(
        url="http://127.0.0.1:8200",
        namespace=None,
        auth_backend=backend,
        default_kv_version=1,
    )
    vault.token = SecretStr("root-token")

    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"data": {"FOO": "BAR"}})
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)

    vault.session = MagicMock()
    vault.session.get = MagicMock(return_value=response)

    secrets = await vault.get_secrets("secret/data/test", kv_version=1)

    vault.session.get.assert_called_once_with(
        "http://127.0.0.1:8200/v1/secret/test",
        headers={"X-Vault-Token": "root-token"},
    )
    assert secrets["FOO"].get_secret_value() == "BAR"


def test_jwt_auth_backend_builds_payload():
    backend = JwtAuthBackend(role="dev", jwt=SecretStr("signed-jwt"))

    assert backend.build_login_payload() == {
        "role": "dev",
        "jwt": "signed-jwt",
    }
    assert backend.login_path == "auth/jwt/login"


def test_oidc_auth_backend_builds_payload():
    backend = OidcAuthBackend(
        role="dev",
        jwt=SecretStr("id-token"),
        distributed_claim_access_token=SecretStr("graph-token"),
    )

    assert backend.build_login_payload() == {
        "role": "dev",
        "jwt": "id-token",
        "distributed_claim_access_token": "graph-token",
    }
    assert backend.login_path == "auth/oidc/login"


def test_oidc_auth_backend_prefers_env_jwt(monkeypatch):
    monkeypatch.setenv("VAULT_OIDC_JWT", "inline-oidc-jwt")

    jwt = OidcAuthBackend.resolve_jwt()

    assert jwt.get_secret_value() == "inline-oidc-jwt"


def test_oidc_auth_backend_accepts_id_token_env(monkeypatch):
    monkeypatch.delenv("VAULT_OIDC_JWT", raising=False)
    monkeypatch.setenv("VAULT_OIDC_ID_TOKEN", "id-token-value")

    jwt = OidcAuthBackend.resolve_jwt()

    assert jwt.get_secret_value() == "id-token-value"


def test_cert_auth_backend_builds_payload():
    backend = CertAuthBackend(
        client_cert_path="/tmp/cert.pem",
        client_key_path="/tmp/key.pem",
        cert_name="web",
    )

    assert backend.build_login_payload() == {"name": "web"}
    assert backend.login_path == "auth/cert/login"


def test_cert_auth_backend_omits_name_when_unset():
    backend = CertAuthBackend(
        client_cert_path="/tmp/cert.pem",
        client_key_path="/tmp/key.pem",
    )

    assert backend.build_login_payload() == {}


def test_cert_auth_backend_loads_client_ssl(tmp_path):
    cert_file = tmp_path / "cert.pem"
    key_file = tmp_path / "key.pem"
    cert_file.write_text("cert", encoding="utf-8")
    key_file.write_text("key", encoding="utf-8")

    backend = CertAuthBackend(
        client_cert_path=str(cert_file),
        client_key_path=str(key_file),
    )

    with pytest.raises(ssl.SSLError):
        backend.client_ssl_for_login


def test_ldap_auth_backend_builds_payload():
    backend = LdapAuthBackend(
        username="mitchellh",
        password=SecretStr("secret"),
        mount="corp-ldap",
    )

    assert backend.build_login_payload() == {"password": "secret"}
    assert backend.login_path == "auth/corp-ldap/login/mitchellh"


def test_oci_auth_backend_builds_payload():
    headers = {
        "date": ["Fri, 22 Aug 2019 21:02:19 GMT"],
        "(request-target)": ["get /v1/auth/oci/login/devrole"],
        "host": ["127.0.0.1"],
        "authorization": ["Signature ..."],
    }
    backend = OciAuthBackend(role="devrole", request_headers=headers)

    assert backend.build_login_payload() == {"request_headers": headers}
    assert backend.login_path == "auth/oci/login/devrole"


def test_oci_auth_backend_uses_pre_signed_headers(monkeypatch):
    headers = {
        "date": ["Fri, 22 Aug 2019 21:02:19 GMT"],
        "(request-target)": ["get /v1/auth/oci/login/demo"],
        "host": ["127.0.0.1"],
        "authorization": ["Signature ..."],
    }
    monkeypatch.setenv("VAULT_OCI_REQUEST_HEADERS", json.dumps(headers))

    resolved = OciAuthBackend.resolve_request_headers(
        "demo",
        "http://127.0.0.1:8200",
        "oci",
    )

    assert resolved == headers


def test_get_required_env_vars_for_phase2_methods():
    assert get_required_env_vars_for_method("jwt") == ("VAULT_JWT_ROLE", "VAULT_JWT")
    assert get_required_env_vars_for_method("oidc") == ("VAULT_OIDC_ROLE",)
    assert get_required_env_vars_for_method("cert") == (
        "VAULT_CLIENT_CERT",
        "VAULT_CLIENT_KEY",
    )
    assert get_required_env_vars_for_method("ldap") == (
        "VAULT_LDAP_USERNAME",
        "VAULT_LDAP_PASSWORD",
    )
    assert get_required_env_vars_for_method("oci") == ("VAULT_OCI_ROLE",)


def test_get_auth_backend_from_env_jwt(monkeypatch):
    monkeypatch.setenv("VAULT_AUTH_METHOD", "jwt")
    monkeypatch.setenv("VAULT_JWT_ROLE", "dev")
    monkeypatch.setenv("VAULT_JWT", "signed-jwt")

    backend = get_auth_backend_from_env()

    assert isinstance(backend, JwtAuthBackend)
    assert backend.build_login_payload()["jwt"] == "signed-jwt"


def test_get_auth_backend_from_env_ldap(monkeypatch):
    monkeypatch.setenv("VAULT_AUTH_METHOD", "ldap")
    monkeypatch.setenv("VAULT_LDAP_USERNAME", "alice")
    monkeypatch.setenv("VAULT_LDAP_PASSWORD", "secret")

    backend = get_auth_backend_from_env()

    assert isinstance(backend, LdapAuthBackend)
    assert backend.login_path == "auth/ldap/login/alice"


def test_get_auth_backend_from_env_oci(monkeypatch):
    headers = {
        "date": ["Fri, 22 Aug 2019 21:02:19 GMT"],
        "(request-target)": ["get /v1/auth/oci/login/demo"],
        "host": ["127.0.0.1"],
        "authorization": ["Signature ..."],
    }
    monkeypatch.setenv("VAULT_AUTH_METHOD", "oci")
    monkeypatch.setenv("VAULT_OCI_ROLE", "demo")
    monkeypatch.setenv("VAULT_OCI_REQUEST_HEADERS", json.dumps(headers))

    backend = get_auth_backend_from_env()

    assert isinstance(backend, OciAuthBackend)
    assert backend.request_headers == headers


@pytest.mark.asyncio
async def test_internal_http_vault_ldap_login():
    backend = LdapAuthBackend(
        username="alice",
        password=SecretStr("secret"),
    )
    vault = InternalHttpVault(
        url="http://127.0.0.1:8200",
        namespace=None,
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
        "http://127.0.0.1:8200/v1/auth/ldap/login/alice",
        json={"password": "secret"},
        headers={},
    )
    assert vault.token.get_secret_value() == "vault-token"


@pytest.mark.asyncio
async def test_internal_http_vault_cert_login_uses_mtls(monkeypatch):
    mock_ssl_context = ssl.create_default_context()
    monkeypatch.setattr(
        CertAuthBackend,
        "client_ssl_for_login",
        PropertyMock(return_value=mock_ssl_context),
    )
    backend = CertAuthBackend(
        client_cert_path="/tmp/cert.pem",
        client_key_path="/tmp/key.pem",
        cert_name="web",
    )

    vault = InternalHttpVault(
        url="https://127.0.0.1:8200",
        namespace=None,
        auth_backend=backend,
    )

    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"auth": {"client_token": "vault-token"}})
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)

    login_session = MagicMock()
    login_session.post = MagicMock(return_value=response)
    login_session.__aenter__ = AsyncMock(return_value=login_session)
    login_session.__aexit__ = AsyncMock(return_value=False)

    vault.session = AsyncMock()
    vault.session.closed = False

    session_factory = MagicMock(return_value=login_session)
    monkeypatch.setattr(
        "pydantic2_settings_vault.shared.infrastructure.vault_http.ClientSession",
        session_factory,
    )

    await vault.authenticate()

    session_factory.assert_called_once()
    login_session.post.assert_called_once_with(
        "https://127.0.0.1:8200/v1/auth/cert/login",
        json={"name": "web"},
        headers={},
    )
    vault.session.post.assert_not_called()
    assert vault.token.get_secret_value() == "vault-token"


def test_userpass_auth_backend_builds_payload():
    backend = UserpassAuthBackend(
        username="alice",
        password=SecretStr("secret"),
    )

    assert backend.build_login_payload() == {"password": "secret"}
    assert backend.login_path == "auth/userpass/login/alice"


def test_github_auth_backend_builds_payload():
    backend = GithubAuthBackend(token=SecretStr("ghp_token"))

    assert backend.build_login_payload() == {"token": "ghp_token"}
    assert backend.login_path == "auth/github/login"


def test_okta_auth_backend_builds_payload():
    backend = OktaAuthBackend(
        username="fred",
        password=SecretStr("Password!"),
        totp="123456",
        mfa_provider="OKTA",
    )

    assert backend.build_login_payload() == {
        "password": "Password!",
        "totp": "123456",
        "provider": "OKTA",
    }
    assert backend.login_path == "auth/okta/login/fred"


def test_kerberos_auth_backend_uses_negotiate_header():
    backend = KerberosAuthBackend(spnego_token="YIIFSw...")

    assert backend.build_login_payload() == {}
    assert backend.login_headers == {"Authorization": "Negotiate YIIFSw..."}
    assert backend.login_path == "auth/kerberos/login"


def test_radius_auth_backend_builds_payload():
    backend = RadiusAuthBackend(
        username="vishal",
        password=SecretStr("Password!"),
    )

    assert backend.build_login_payload() == {"password": "Password!"}
    assert backend.login_path == "auth/radius/login/vishal"


def test_alicloud_auth_backend_requires_pre_signed_payload(monkeypatch):
    monkeypatch.delenv("VAULT_ALICLOUD_IDENTITY_REQUEST_URL", raising=False)
    monkeypatch.delenv("VAULT_ALICLOUD_IDENTITY_REQUEST_HEADERS", raising=False)

    with pytest.raises(ValueError, match="VAULT_ALICLOUD_IDENTITY_REQUEST_URL"):
        AlicloudAuthBackend.resolve_login_payload("dev-role")


def test_alicloud_auth_backend_uses_pre_signed_payload(monkeypatch):
    monkeypatch.setenv("VAULT_ALICLOUD_IDENTITY_REQUEST_URL", "url")
    monkeypatch.setenv("VAULT_ALICLOUD_IDENTITY_REQUEST_HEADERS", "headers")

    payload = AlicloudAuthBackend.resolve_login_payload("dev-role")

    assert payload == {
        "role": "dev-role",
        "identity_request_url": "url",
        "identity_request_headers": "headers",
    }


def test_cf_auth_backend_reads_cert_from_file(tmp_path, monkeypatch):
    cert_file = tmp_path / "instance.crt"
    cert_file.write_text("cert-from-file", encoding="utf-8")
    monkeypatch.setenv("CF_INSTANCE_CERT", str(cert_file))
    monkeypatch.setenv("VAULT_CF_SIGNING_TIME", "2019-05-20T22:08:40Z")
    monkeypatch.setenv("VAULT_CF_SIGNATURE", "v1:signature")

    payload = CfAuthBackend.resolve_login_payload("test-role")

    assert payload["cf_instance_cert"] == "cert-from-file"


def test_cf_auth_backend_signs_with_instance_key(tmp_path, monkeypatch):
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_file = tmp_path / "instance.crt"
    key_file = tmp_path / "instance.key"
    cert_file.write_text("cert-body", encoding="utf-8")
    key_file.write_bytes(key_pem)
    monkeypatch.setenv("CF_INSTANCE_CERT", str(cert_file))
    monkeypatch.setenv("CF_INSTANCE_KEY", str(key_file))

    payload = CfAuthBackend.resolve_login_payload("test-role")

    assert payload["role"] == "test-role"
    assert payload["cf_instance_cert"] == "cert-body"
    assert payload["signature"].startswith("v1:")


def test_cf_auth_backend_uses_pre_signed_payload(monkeypatch):
    monkeypatch.setenv("VAULT_CF_INSTANCE_CERT", "cert-body")
    monkeypatch.setenv("VAULT_CF_SIGNING_TIME", "2019-05-20T22:08:40Z")
    monkeypatch.setenv("VAULT_CF_SIGNATURE", "v1:signature")

    payload = CfAuthBackend.resolve_login_payload("test-role")

    assert payload == {
        "role": "test-role",
        "cf_instance_cert": "cert-body",
        "signing_time": "2019-05-20T22:08:40Z",
        "signature": "v1:signature",
    }


def test_cf_auth_backend_generates_signature(monkeypatch):
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_body = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
    signing_time = "2019-05-20T22:08:40Z"

    payload = CfAuthBackend.generate_login_payload(
        "test-role",
        cert_body,
        private_key_pem,
        signing_time=signing_time,
    )

    assert payload["role"] == "test-role"
    assert payload["cf_instance_cert"] == cert_body
    assert payload["signing_time"] == signing_time
    assert payload["signature"].startswith("v1:")

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, utils

    to_sign = f"{signing_time}{cert_body}test-role"
    digest = hashes.Hash(hashes.SHA256())
    digest.update(to_sign.encode())
    hashed = digest.finalize()
    signature_bytes = base64.b64decode(payload["signature"][3:])
    public_key = private_key.public_key()
    public_key.verify(
        signature_bytes,
        hashed,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH,
        ),
        utils.Prehashed(hashes.SHA256()),
    )


def test_pcf_auth_backend_uses_pcf_mount():
    backend = PcfAuthBackend(
        role="test-role",
        cf_instance_cert="cert-body",
        signing_time="2019-05-20T22:08:40Z",
        signature="v1:signature",
    )

    assert backend.login_path == "auth/pcf/login"
    assert backend.build_login_payload()["role"] == "test-role"


def test_get_required_env_vars_for_phase3_methods():
    assert get_required_env_vars_for_method("userpass") == (
        "VAULT_USERPASS_USERNAME",
        "VAULT_USERPASS_PASSWORD",
    )
    assert get_required_env_vars_for_method("github") == ("VAULT_GITHUB_TOKEN",)
    assert get_required_env_vars_for_method("okta") == (
        "VAULT_OKTA_USERNAME",
        "VAULT_OKTA_PASSWORD",
    )
    assert get_required_env_vars_for_method("kerberos") == ("VAULT_KERBEROS_TOKEN",)
    assert get_required_env_vars_for_method("radius") == (
        "VAULT_RADIUS_USERNAME",
        "VAULT_RADIUS_PASSWORD",
    )
    assert get_required_env_vars_for_method("alicloud") == ("VAULT_ALICLOUD_ROLE",)
    assert get_required_env_vars_for_method("cf") == ("VAULT_CF_ROLE",)
    assert get_required_env_vars_for_method("pcf") == ("VAULT_CF_ROLE",)


def test_get_auth_backend_from_env_userpass(monkeypatch):
    monkeypatch.setenv("VAULT_AUTH_METHOD", "userpass")
    monkeypatch.setenv("VAULT_USERPASS_USERNAME", "alice")
    monkeypatch.setenv("VAULT_USERPASS_PASSWORD", "secret")

    backend = get_auth_backend_from_env()

    assert isinstance(backend, UserpassAuthBackend)
    assert backend.login_path == "auth/userpass/login/alice"


def test_get_auth_backend_from_env_github(monkeypatch):
    monkeypatch.setenv("VAULT_AUTH_METHOD", "github")
    monkeypatch.setenv("VAULT_GITHUB_TOKEN", "ghp_token")

    backend = get_auth_backend_from_env()

    assert isinstance(backend, GithubAuthBackend)


def test_get_auth_backend_from_env_okta(monkeypatch):
    monkeypatch.setenv("VAULT_AUTH_METHOD", "okta")
    monkeypatch.setenv("VAULT_OKTA_USERNAME", "fred")
    monkeypatch.setenv("VAULT_OKTA_PASSWORD", "Password!")
    monkeypatch.setenv("VAULT_OKTA_TOTP", "123456")

    backend = get_auth_backend_from_env()

    assert isinstance(backend, OktaAuthBackend)
    assert backend.build_login_payload()["totp"] == "123456"


def test_get_auth_backend_from_env_radius(monkeypatch):
    monkeypatch.setenv("VAULT_AUTH_METHOD", "radius")
    monkeypatch.setenv("VAULT_RADIUS_USERNAME", "vishal")
    monkeypatch.setenv("VAULT_RADIUS_PASSWORD", "Password!")

    backend = get_auth_backend_from_env()

    assert isinstance(backend, RadiusAuthBackend)
    assert backend.login_path == "auth/radius/login/vishal"


def test_get_auth_backend_from_env_kerberos(monkeypatch):
    monkeypatch.setenv("VAULT_AUTH_METHOD", "kerberos")
    monkeypatch.setenv("VAULT_KERBEROS_TOKEN", "spnego-token")

    backend = get_auth_backend_from_env()

    assert isinstance(backend, KerberosAuthBackend)
    assert backend.login_headers["Authorization"] == "Negotiate spnego-token"


def test_get_auth_backend_from_env_alicloud(monkeypatch):
    monkeypatch.setenv("VAULT_AUTH_METHOD", "alicloud")
    monkeypatch.setenv("VAULT_ALICLOUD_ROLE", "dev-role")
    monkeypatch.setenv("VAULT_ALICLOUD_IDENTITY_REQUEST_URL", "url")
    monkeypatch.setenv("VAULT_ALICLOUD_IDENTITY_REQUEST_HEADERS", "headers")

    backend = get_auth_backend_from_env()

    assert isinstance(backend, AlicloudAuthBackend)
    assert backend.build_login_payload()["identity_request_url"] == "url"


def test_get_auth_backend_from_env_cf(monkeypatch):
    monkeypatch.setenv("VAULT_AUTH_METHOD", "cf")
    monkeypatch.setenv("VAULT_CF_ROLE", "test-role")
    monkeypatch.setenv("VAULT_CF_INSTANCE_CERT", "cert-body")
    monkeypatch.setenv("VAULT_CF_SIGNING_TIME", "2019-05-20T22:08:40Z")
    monkeypatch.setenv("VAULT_CF_SIGNATURE", "v1:signature")

    backend = get_auth_backend_from_env()

    assert isinstance(backend, CfAuthBackend)
    assert backend.signature == "v1:signature"


def test_get_auth_backend_from_env_pcf(monkeypatch):
    monkeypatch.setenv("VAULT_AUTH_METHOD", "pcf")
    monkeypatch.setenv("VAULT_CF_ROLE", "test-role")
    monkeypatch.setenv("VAULT_CF_INSTANCE_CERT", "cert-body")
    monkeypatch.setenv("VAULT_CF_SIGNING_TIME", "2019-05-20T22:08:40Z")
    monkeypatch.setenv("VAULT_CF_SIGNATURE", "v1:signature")

    backend = get_auth_backend_from_env()

    assert isinstance(backend, PcfAuthBackend)
    assert backend.login_path == "auth/pcf/login"


@pytest.mark.asyncio
async def test_internal_http_vault_kerberos_login():
    backend = KerberosAuthBackend(spnego_token="spnego-token")
    vault = InternalHttpVault(
        url="http://127.0.0.1:8200",
        namespace=None,
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
        "http://127.0.0.1:8200/v1/auth/kerberos/login",
        json={},
        headers={"Authorization": "Negotiate spnego-token"},
    )
    assert vault.token.get_secret_value() == "vault-token"
