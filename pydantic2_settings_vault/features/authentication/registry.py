from __future__ import annotations

import os
from typing import Type

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
    VaultAuthBackend,
)

AUTH_METHOD_ENV_VAR = "VAULT_AUTH_METHOD"
AUTH_MOUNT_ENV_VAR = "VAULT_AUTH_MOUNT"

_AUTH_BACKEND_BY_METHOD: dict[str, Type[VaultAuthBackend]] = {
    "approle": AppRoleAuthBackend,
    "token": TokenAuthBackend,
    "kubernetes": KubernetesAuthBackend,
    "aws": AwsAuthBackend,
    "gcp": GcpAuthBackend,
    "azure": AzureAuthBackend,
    "jwt": JwtAuthBackend,
    "oidc": OidcAuthBackend,
    "cert": CertAuthBackend,
    "ldap": LdapAuthBackend,
    "oci": OciAuthBackend,
    "userpass": UserpassAuthBackend,
    "github": GithubAuthBackend,
    "okta": OktaAuthBackend,
    "kerberos": KerberosAuthBackend,
    "radius": RadiusAuthBackend,
    "alicloud": AlicloudAuthBackend,
    "cf": CfAuthBackend,
    "pcf": PcfAuthBackend,
}


def resolve_auth_method() -> str:
    return os.getenv(AUTH_METHOD_ENV_VAR, AppRoleAuthBackend.method_name).lower()


def get_required_env_vars_for_method(method: str | None = None) -> tuple[str, ...]:
    resolved_method = (method or resolve_auth_method()).lower()
    backend_cls = _AUTH_BACKEND_BY_METHOD.get(resolved_method)
    if backend_cls is None:
        supported = ", ".join(sorted(_AUTH_BACKEND_BY_METHOD))
        raise ValueError(
            f"Unsupported Vault auth method {resolved_method!r}. "
            f"Supported methods: {supported}."
        )
    return backend_cls.required_env_vars()


def _resolve_mount(backend_cls: Type[VaultAuthBackend]) -> str | None:
    return os.getenv(AUTH_MOUNT_ENV_VAR)


def get_auth_backend_from_env() -> VaultAuthBackend:
    method = resolve_auth_method()
    backend_cls = _AUTH_BACKEND_BY_METHOD.get(method)
    if backend_cls is None:
        supported = ", ".join(sorted(_AUTH_BACKEND_BY_METHOD))
        raise ValueError(
            f"Unsupported Vault auth method {method!r}. Supported methods: {supported}."
        )

    mount = _resolve_mount(backend_cls)
    resolved_mount = mount or backend_cls.default_mount

    if backend_cls is TokenAuthBackend:
        return TokenAuthBackend(
            token=SecretStr(os.environ["VAULT_TOKEN"]),
            mount=mount,
        )

    if backend_cls is AppRoleAuthBackend:
        return AppRoleAuthBackend(
            role_id=SecretStr(os.environ["VAULT_ROLE_ID"]),
            secret_id=SecretStr(os.environ["VAULT_SECRET_ID"]),
            mount=mount,
        )

    if backend_cls is KubernetesAuthBackend:
        return KubernetesAuthBackend(
            role=os.environ["VAULT_K8S_ROLE"],
            jwt=KubernetesAuthBackend.resolve_jwt(),
            mount=mount,
        )

    if backend_cls is AwsAuthBackend:
        role = os.environ["VAULT_AWS_ROLE"]
        return AwsAuthBackend(
            role=role,
            mount=mount,
            iam_server_id=os.getenv("VAULT_AWS_IAM_SERVER_ID"),
            login_payload=AwsAuthBackend.resolve_login_payload(role),
        )

    if backend_cls is GcpAuthBackend:
        role = os.environ["VAULT_GCP_ROLE"]
        return GcpAuthBackend(
            role=role,
            jwt=GcpAuthBackend.resolve_jwt(role),
            mount=mount,
        )

    if backend_cls is AzureAuthBackend:
        return AzureAuthBackend(
            role=os.environ["VAULT_AZURE_ROLE"],
            jwt=AzureAuthBackend.resolve_jwt(),
            mount=mount,
        )

    if backend_cls is JwtAuthBackend:
        return JwtAuthBackend(
            role=os.environ["VAULT_JWT_ROLE"],
            jwt=SecretStr(os.environ["VAULT_JWT"]),
            mount=mount,
        )

    if backend_cls is OidcAuthBackend:
        distributed_token = os.getenv("VAULT_OIDC_DISTRIBUTED_CLAIM_ACCESS_TOKEN")
        return OidcAuthBackend(
            role=os.environ["VAULT_OIDC_ROLE"],
            jwt=OidcAuthBackend.resolve_jwt(),
            mount=mount,
            distributed_claim_access_token=(
                SecretStr(distributed_token) if distributed_token else None
            ),
        )

    if backend_cls is CertAuthBackend:
        key_password = os.getenv("VAULT_CLIENT_KEY_PASSWORD")
        return CertAuthBackend(
            client_cert_path=os.environ["VAULT_CLIENT_CERT"],
            client_key_path=os.environ["VAULT_CLIENT_KEY"],
            mount=mount,
            cert_name=os.getenv("VAULT_CERT_NAME"),
            client_key_password=(SecretStr(key_password) if key_password else None),
        )

    if backend_cls is LdapAuthBackend:
        return LdapAuthBackend(
            username=os.environ["VAULT_LDAP_USERNAME"],
            password=SecretStr(os.environ["VAULT_LDAP_PASSWORD"]),
            mount=mount,
        )

    if backend_cls is OciAuthBackend:
        role = os.environ["VAULT_OCI_ROLE"]
        vault_url = os.getenv("VAULT_URL", "http://127.0.0.1:8200")
        return OciAuthBackend(
            role=role,
            request_headers=OciAuthBackend.resolve_request_headers(
                role,
                vault_url,
                resolved_mount,
            ),
            mount=mount,
        )

    if backend_cls is UserpassAuthBackend:
        return UserpassAuthBackend(
            username=os.environ["VAULT_USERPASS_USERNAME"],
            password=SecretStr(os.environ["VAULT_USERPASS_PASSWORD"]),
            mount=mount,
        )

    if backend_cls is GithubAuthBackend:
        return GithubAuthBackend(
            token=SecretStr(os.environ["VAULT_GITHUB_TOKEN"]),
            mount=mount,
        )

    if backend_cls is OktaAuthBackend:
        return OktaAuthBackend(
            username=os.environ["VAULT_OKTA_USERNAME"],
            password=SecretStr(os.environ["VAULT_OKTA_PASSWORD"]),
            mount=mount,
            totp=os.getenv("VAULT_OKTA_TOTP"),
            mfa_provider=os.getenv("VAULT_OKTA_MFA_PROVIDER"),
        )

    if backend_cls is KerberosAuthBackend:
        return KerberosAuthBackend(
            spnego_token=os.environ["VAULT_KERBEROS_TOKEN"],
            mount=mount,
        )

    if backend_cls is RadiusAuthBackend:
        return RadiusAuthBackend(
            username=os.environ["VAULT_RADIUS_USERNAME"],
            password=SecretStr(os.environ["VAULT_RADIUS_PASSWORD"]),
            mount=mount,
        )

    if backend_cls is AlicloudAuthBackend:
        role = os.environ["VAULT_ALICLOUD_ROLE"]
        return AlicloudAuthBackend(
            role=role,
            mount=mount,
            login_payload=AlicloudAuthBackend.resolve_login_payload(role),
        )

    if backend_cls is CfAuthBackend:
        role = os.environ["VAULT_CF_ROLE"]
        login_payload = CfAuthBackend.resolve_login_payload(role)
        return CfAuthBackend(
            role=role,
            cf_instance_cert=login_payload["cf_instance_cert"],
            signing_time=login_payload["signing_time"],
            signature=login_payload["signature"],
            mount=mount,
        )

    if backend_cls is PcfAuthBackend:
        role = os.environ["VAULT_CF_ROLE"]
        login_payload = PcfAuthBackend.resolve_login_payload(role)
        return PcfAuthBackend(
            role=role,
            cf_instance_cert=login_payload["cf_instance_cert"],
            signing_time=login_payload["signing_time"],
            signature=login_payload["signature"],
            mount=mount,
        )

    raise ValueError(f"Unsupported Vault auth method {method!r}.")
