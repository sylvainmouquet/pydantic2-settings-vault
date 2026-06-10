from __future__ import annotations

import base64
import json
import os
import ssl
from abc import ABC, abstractmethod
from email.utils import formatdate
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlparse

import certifi
from pydantic import SecretStr

DEFAULT_K8S_JWT_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"


class VaultAuthBackend(ABC):
    """Protocol for Vault authentication backends."""

    method_name: ClassVar[str]
    default_mount: ClassVar[str]

    def __init__(self, mount: str | None = None) -> None:
        self.mount = mount or self.default_mount

    @classmethod
    @abstractmethod
    def required_env_vars(cls) -> tuple[str, ...]:
        """Environment variables required for this auth method."""

    @property
    def uses_login(self) -> bool:
        """Return False when the token is provided directly (no login call)."""
        return True

    @property
    def direct_token(self) -> SecretStr | None:
        """Return a pre-issued token when ``uses_login`` is False."""
        return None

    @property
    def login_path(self) -> str:
        return f"auth/{self.mount}/login"

    @property
    def client_ssl_for_login(self) -> ssl.SSLContext | None:
        """Return an SSL context with a client certificate for mTLS login, if required."""
        return None

    @abstractmethod
    def build_login_payload(self) -> dict[str, Any]:
        """Build the JSON body for the auth login request."""

    @property
    def login_headers(self) -> dict[str, str]:
        """Return extra headers for the auth login request."""
        return {}

    @classmethod
    def display_name(cls) -> str:
        return cls.method_name


class TokenAuthBackend(VaultAuthBackend):
    method_name = "token"
    default_mount = "token"

    def __init__(self, token: SecretStr, mount: str | None = None) -> None:
        super().__init__(mount=mount)
        self._token = token

    @classmethod
    def required_env_vars(cls) -> tuple[str, ...]:
        return ("VAULT_TOKEN",)

    @property
    def uses_login(self) -> bool:
        return False

    @property
    def direct_token(self) -> SecretStr:
        return self._token

    def build_login_payload(self) -> dict[str, Any]:
        raise RuntimeError("Token auth does not use a login endpoint")


class AppRoleAuthBackend(VaultAuthBackend):
    method_name = "approle"
    default_mount = "approle"

    def __init__(
        self,
        role_id: SecretStr,
        secret_id: SecretStr,
        mount: str | None = None,
    ) -> None:
        super().__init__(mount=mount)
        self.role_id = role_id
        self.secret_id = secret_id

    @classmethod
    def required_env_vars(cls) -> tuple[str, ...]:
        return ("VAULT_ROLE_ID", "VAULT_SECRET_ID")

    def build_login_payload(self) -> dict[str, Any]:
        return {
            "role_id": self.role_id.get_secret_value(),
            "secret_id": self.secret_id.get_secret_value(),
        }


class KubernetesAuthBackend(VaultAuthBackend):
    method_name = "kubernetes"
    default_mount = "kubernetes"

    def __init__(
        self,
        role: str,
        jwt: SecretStr,
        mount: str | None = None,
    ) -> None:
        super().__init__(mount=mount)
        self.role = role
        self.jwt = jwt

    @classmethod
    def required_env_vars(cls) -> tuple[str, ...]:
        return ("VAULT_K8S_ROLE",)

    @classmethod
    def resolve_jwt(cls) -> SecretStr:
        if jwt_value := os.getenv("VAULT_K8S_JWT"):
            return SecretStr(jwt_value)

        jwt_path = os.getenv("VAULT_K8S_JWT_PATH", DEFAULT_K8S_JWT_PATH)
        jwt_file = Path(jwt_path)
        if not jwt_file.is_file():
            raise ValueError(
                "Kubernetes auth requires VAULT_K8S_JWT or a readable service-account "
                f"token at {jwt_path!r}."
            )

        return SecretStr(jwt_file.read_text(encoding="utf-8").strip())

    def build_login_payload(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "jwt": self.jwt.get_secret_value(),
        }


class AwsAuthBackend(VaultAuthBackend):
    method_name = "aws"
    default_mount = "aws"

    def __init__(
        self,
        role: str,
        mount: str | None = None,
        *,
        iam_server_id: str | None = None,
        login_payload: dict[str, str] | None = None,
    ) -> None:
        super().__init__(mount=mount)
        self.role = role
        self.iam_server_id = iam_server_id
        self._login_payload = login_payload

    @classmethod
    def required_env_vars(cls) -> tuple[str, ...]:
        return ("VAULT_AWS_ROLE",)

    @classmethod
    def generate_iam_login_payload(
        cls,
        role: str,
        *,
        iam_server_id: str | None = None,
    ) -> dict[str, str]:
        try:
            import botocore.session
        except ImportError as exc:
            raise ImportError(
                "AWS auth requires botocore. Install with "
                "'pip install pydantic2-settings-vault[aws]' or set "
                "VAULT_AWS_IAM_REQUEST_URL, VAULT_AWS_IAM_REQUEST_BODY, and "
                "VAULT_AWS_IAM_REQUEST_HEADERS with a pre-signed STS request."
            ) from exc

        session = botocore.session.get_session()
        client = session.create_client("sts")
        endpoint = client._endpoint
        operation_model = client._service_model.operation_model("GetCallerIdentity")
        request_dict = client._convert_to_request_dict({}, operation_model)

        if iam_server_id:
            request_dict["headers"]["X-Vault-AWS-IAM-Server-ID"] = iam_server_id

        request = endpoint.create_request(request_dict, operation_model)
        headers = {key: [value] for key, value in dict(request.headers).items()}

        payload = {
            "role": role,
            "iam_http_request_method": request.method,
            "iam_request_url": base64.b64encode(request.url.encode()).decode(),
            "iam_request_body": base64.b64encode(
                (request.body or "").encode()
            ).decode(),
            "iam_request_headers": base64.b64encode(
                json.dumps(headers).encode()
            ).decode(),
        }
        return payload

    @classmethod
    def resolve_login_payload(cls, role: str) -> dict[str, str]:
        request_url = os.getenv("VAULT_AWS_IAM_REQUEST_URL")
        request_body = os.getenv("VAULT_AWS_IAM_REQUEST_BODY")
        request_headers = os.getenv("VAULT_AWS_IAM_REQUEST_HEADERS")

        if request_url and request_body and request_headers:
            return {
                "role": role,
                "iam_http_request_method": os.getenv(
                    "VAULT_AWS_IAM_REQUEST_METHOD", "POST"
                ),
                "iam_request_url": request_url,
                "iam_request_body": request_body,
                "iam_request_headers": request_headers,
            }

        iam_server_id = os.getenv("VAULT_AWS_IAM_SERVER_ID")
        if not iam_server_id:
            vault_url = os.getenv("VAULT_URL", "http://127.0.0.1:8200")
            iam_server_id = urlparse(vault_url).hostname

        return cls.generate_iam_login_payload(role, iam_server_id=iam_server_id)

    def build_login_payload(self) -> dict[str, Any]:
        if self._login_payload is not None:
            return self._login_payload
        return self.resolve_login_payload(self.role)


class GcpAuthBackend(VaultAuthBackend):
    method_name = "gcp"
    default_mount = "gcp"

    def __init__(
        self,
        role: str,
        jwt: SecretStr,
        mount: str | None = None,
    ) -> None:
        super().__init__(mount=mount)
        self.role = role
        self.jwt = jwt

    @classmethod
    def required_env_vars(cls) -> tuple[str, ...]:
        return ("VAULT_GCP_ROLE",)

    @classmethod
    def resolve_jwt(cls, role: str) -> SecretStr:
        if jwt_value := os.getenv("VAULT_GCP_JWT"):
            return SecretStr(jwt_value)

        try:
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account
        except ImportError as exc:
            raise ImportError(
                "GCP auth requires google-auth. Install with "
                "'pip install pydantic2-settings-vault[gcp]' or set VAULT_GCP_JWT."
            ) from exc

        credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if not credentials_path:
            raise ValueError(
                "GCP auth requires VAULT_GCP_JWT or GOOGLE_APPLICATION_CREDENTIALS "
                "pointing to a service-account key file."
            )

        credentials = service_account.Credentials.from_service_account_file(
            credentials_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        credentials.refresh(Request())
        if credentials.token is None:
            raise ValueError("Failed to obtain a GCP access token for Vault login.")

        return SecretStr(credentials.token)

    def build_login_payload(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "jwt": self.jwt.get_secret_value(),
        }


class AzureAuthBackend(VaultAuthBackend):
    method_name = "azure"
    default_mount = "azure"

    def __init__(
        self,
        role: str,
        jwt: SecretStr,
        mount: str | None = None,
    ) -> None:
        super().__init__(mount=mount)
        self.role = role
        self.jwt = jwt

    @classmethod
    def required_env_vars(cls) -> tuple[str, ...]:
        return ("VAULT_AZURE_ROLE",)

    @classmethod
    def resolve_jwt(cls) -> SecretStr:
        if jwt_value := os.getenv("VAULT_AZURE_JWT"):
            return SecretStr(jwt_value)

        try:
            from azure.identity import DefaultAzureCredential
        except ImportError as exc:
            raise ImportError(
                "Azure auth requires azure-identity. Install with "
                "'pip install pydantic2-settings-vault[azure]' or set VAULT_AZURE_JWT."
            ) from exc

        resource = os.getenv(
            "VAULT_AZURE_RESOURCE", "https://management.azure.com/.default"
        )
        credential = DefaultAzureCredential()
        token = credential.get_token(resource)
        return SecretStr(token.token)

    def build_login_payload(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "jwt": self.jwt.get_secret_value(),
        }


class JwtAuthBackend(VaultAuthBackend):
    method_name = "jwt"
    default_mount = "jwt"

    def __init__(
        self,
        role: str,
        jwt: SecretStr,
        mount: str | None = None,
    ) -> None:
        super().__init__(mount=mount)
        self.role = role
        self.jwt = jwt

    @classmethod
    def required_env_vars(cls) -> tuple[str, ...]:
        return ("VAULT_JWT_ROLE", "VAULT_JWT")

    def build_login_payload(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "jwt": self.jwt.get_secret_value(),
        }


class OidcAuthBackend(VaultAuthBackend):
    method_name = "oidc"
    default_mount = "oidc"

    def __init__(
        self,
        role: str,
        jwt: SecretStr,
        mount: str | None = None,
        *,
        distributed_claim_access_token: SecretStr | None = None,
    ) -> None:
        super().__init__(mount=mount)
        self.role = role
        self.jwt = jwt
        self.distributed_claim_access_token = distributed_claim_access_token

    @classmethod
    def required_env_vars(cls) -> tuple[str, ...]:
        return ("VAULT_OIDC_ROLE",)

    @classmethod
    def resolve_jwt(cls) -> SecretStr:
        if jwt_value := os.getenv("VAULT_OIDC_JWT"):
            return SecretStr(jwt_value)
        if jwt_value := os.getenv("VAULT_OIDC_ID_TOKEN"):
            return SecretStr(jwt_value)
        raise ValueError("OIDC auth requires VAULT_OIDC_JWT or VAULT_OIDC_ID_TOKEN.")

    def build_login_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "role": self.role,
            "jwt": self.jwt.get_secret_value(),
        }
        if self.distributed_claim_access_token is not None:
            payload["distributed_claim_access_token"] = (
                self.distributed_claim_access_token.get_secret_value()
            )
        return payload


class CertAuthBackend(VaultAuthBackend):
    method_name = "cert"
    default_mount = "cert"

    def __init__(
        self,
        client_cert_path: str,
        client_key_path: str,
        mount: str | None = None,
        *,
        cert_name: str | None = None,
        client_key_password: SecretStr | None = None,
    ) -> None:
        super().__init__(mount=mount)
        self.client_cert_path = client_cert_path
        self.client_key_path = client_key_path
        self.cert_name = cert_name
        self.client_key_password = client_key_password

    @classmethod
    def required_env_vars(cls) -> tuple[str, ...]:
        return ("VAULT_CLIENT_CERT", "VAULT_CLIENT_KEY")

    @property
    def client_ssl_for_login(self) -> ssl.SSLContext:
        context = ssl.create_default_context(cafile=certifi.where())
        password = (
            self.client_key_password.get_secret_value()
            if self.client_key_password is not None
            else None
        )
        context.load_cert_chain(
            certfile=self.client_cert_path,
            keyfile=self.client_key_path,
            password=password,
        )
        return context

    def build_login_payload(self) -> dict[str, Any]:
        if self.cert_name:
            return {"name": self.cert_name}
        return {}


class LdapAuthBackend(VaultAuthBackend):
    method_name = "ldap"
    default_mount = "ldap"

    def __init__(
        self,
        username: str,
        password: SecretStr,
        mount: str | None = None,
    ) -> None:
        super().__init__(mount=mount)
        self.username = username
        self.password = password

    @classmethod
    def required_env_vars(cls) -> tuple[str, ...]:
        return ("VAULT_LDAP_USERNAME", "VAULT_LDAP_PASSWORD")

    @property
    def login_path(self) -> str:
        return f"auth/{self.mount}/login/{self.username}"

    def build_login_payload(self) -> dict[str, Any]:
        return {"password": self.password.get_secret_value()}


class OciAuthBackend(VaultAuthBackend):
    method_name = "oci"
    default_mount = "oci"

    def __init__(
        self,
        role: str,
        request_headers: dict[str, list[str]],
        mount: str | None = None,
    ) -> None:
        super().__init__(mount=mount)
        self.role = role
        self.request_headers = request_headers

    @classmethod
    def required_env_vars(cls) -> tuple[str, ...]:
        return ("VAULT_OCI_ROLE",)

    @property
    def login_path(self) -> str:
        return f"auth/{self.mount}/login/{self.role}"

    @classmethod
    def resolve_request_headers(
        cls,
        role: str,
        vault_url: str,
        mount: str,
    ) -> dict[str, list[str]]:
        if headers_json := os.getenv("VAULT_OCI_REQUEST_HEADERS"):
            headers = json.loads(headers_json)
            if not isinstance(headers, dict):
                raise ValueError(
                    "VAULT_OCI_REQUEST_HEADERS must be a JSON object mapping "
                    "header names to string lists."
                )
            return headers

        try:
            import oci
            import requests
        except ImportError as exc:
            raise ImportError(
                "OCI auth requires the oci package. Install with "
                "'pip install pydantic2-settings-vault[oci]' or set "
                "VAULT_OCI_REQUEST_HEADERS with pre-signed request headers."
            ) from exc

        parsed = urlparse(vault_url)
        host = parsed.hostname or "127.0.0.1"
        if parsed.port and parsed.port not in (80, 443):
            host_header = f"{host}:{parsed.port}"
        else:
            host_header = host

        login_url = f"{vault_url.rstrip('/')}/v1/auth/{mount}/login/{role}"
        request_target = f"get /v1/auth/{mount}/login/{role}"

        auth_type = os.getenv("VAULT_OCI_AUTH_TYPE", "instance").lower()
        if auth_type == "instance":
            signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        elif auth_type == "api_key":
            config = oci.config.from_file(
                file_location=os.getenv("OCI_CONFIG_FILE"),
                profile_name=os.getenv("OCI_CONFIG_PROFILE"),
            )
            signer = oci.signer.Signer(
                tenancy=config["tenancy"],
                user=config["user"],
                fingerprint=config["fingerprint"],
                private_key_file_location=config.get("key_file"),
                pass_phrase=config.get("pass_phrase"),
                private_key_content=config.get("key_content"),
            )
        else:
            raise ValueError(
                "VAULT_OCI_AUTH_TYPE must be 'instance' or 'api_key', "
                f"not {auth_type!r}."
            )

        prepared_request = requests.Request("GET", login_url).prepare()
        prepared_request.headers["date"] = formatdate(usegmt=True)
        signer(prepared_request)

        headers: dict[str, list[str]] = {
            "date": [prepared_request.headers["date"]],
            "(request-target)": [request_target],
            "host": [host_header],
            "authorization": [prepared_request.headers["authorization"]],
        }
        if content_type := prepared_request.headers.get("content-type"):
            headers["content-type"] = [content_type]
        return headers

    def build_login_payload(self) -> dict[str, Any]:
        return {"request_headers": self.request_headers}


class UserpassAuthBackend(VaultAuthBackend):
    method_name = "userpass"
    default_mount = "userpass"

    def __init__(
        self,
        username: str,
        password: SecretStr,
        mount: str | None = None,
    ) -> None:
        super().__init__(mount=mount)
        self.username = username
        self.password = password

    @classmethod
    def required_env_vars(cls) -> tuple[str, ...]:
        return ("VAULT_USERPASS_USERNAME", "VAULT_USERPASS_PASSWORD")

    @property
    def login_path(self) -> str:
        return f"auth/{self.mount}/login/{self.username}"

    def build_login_payload(self) -> dict[str, Any]:
        return {"password": self.password.get_secret_value()}


class GithubAuthBackend(VaultAuthBackend):
    method_name = "github"
    default_mount = "github"

    def __init__(
        self,
        token: SecretStr,
        mount: str | None = None,
    ) -> None:
        super().__init__(mount=mount)
        self.token = token

    @classmethod
    def required_env_vars(cls) -> tuple[str, ...]:
        return ("VAULT_GITHUB_TOKEN",)

    def build_login_payload(self) -> dict[str, Any]:
        return {"token": self.token.get_secret_value()}


class OktaAuthBackend(VaultAuthBackend):
    method_name = "okta"
    default_mount = "okta"

    def __init__(
        self,
        username: str,
        password: SecretStr,
        mount: str | None = None,
        *,
        totp: str | None = None,
        mfa_provider: str | None = None,
    ) -> None:
        super().__init__(mount=mount)
        self.username = username
        self.password = password
        self.totp = totp
        self.mfa_provider = mfa_provider

    @classmethod
    def required_env_vars(cls) -> tuple[str, ...]:
        return ("VAULT_OKTA_USERNAME", "VAULT_OKTA_PASSWORD")

    @property
    def login_path(self) -> str:
        return f"auth/{self.mount}/login/{self.username}"

    def build_login_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"password": self.password.get_secret_value()}
        if self.totp is not None:
            payload["totp"] = self.totp
        if self.mfa_provider is not None:
            payload["provider"] = self.mfa_provider
        return payload


class KerberosAuthBackend(VaultAuthBackend):
    method_name = "kerberos"
    default_mount = "kerberos"

    def __init__(
        self,
        spnego_token: str,
        mount: str | None = None,
    ) -> None:
        super().__init__(mount=mount)
        self.spnego_token = spnego_token

    @classmethod
    def required_env_vars(cls) -> tuple[str, ...]:
        return ("VAULT_KERBEROS_TOKEN",)

    @property
    def login_headers(self) -> dict[str, str]:
        return {"Authorization": f"Negotiate {self.spnego_token}"}

    def build_login_payload(self) -> dict[str, Any]:
        return {}


class RadiusAuthBackend(VaultAuthBackend):
    method_name = "radius"
    default_mount = "radius"

    def __init__(
        self,
        username: str,
        password: SecretStr,
        mount: str | None = None,
    ) -> None:
        super().__init__(mount=mount)
        self.username = username
        self.password = password

    @classmethod
    def required_env_vars(cls) -> tuple[str, ...]:
        return ("VAULT_RADIUS_USERNAME", "VAULT_RADIUS_PASSWORD")

    @property
    def login_path(self) -> str:
        return f"auth/{self.mount}/login/{self.username}"

    def build_login_payload(self) -> dict[str, Any]:
        return {"password": self.password.get_secret_value()}


class AlicloudAuthBackend(VaultAuthBackend):
    method_name = "alicloud"
    default_mount = "alicloud"

    def __init__(
        self,
        role: str,
        mount: str | None = None,
        *,
        login_payload: dict[str, str] | None = None,
    ) -> None:
        super().__init__(mount=mount)
        self.role = role
        self._login_payload = login_payload

    @classmethod
    def required_env_vars(cls) -> tuple[str, ...]:
        return ("VAULT_ALICLOUD_ROLE",)

    @classmethod
    def resolve_login_payload(cls, role: str) -> dict[str, str]:
        request_url = os.getenv("VAULT_ALICLOUD_IDENTITY_REQUEST_URL")
        request_headers = os.getenv("VAULT_ALICLOUD_IDENTITY_REQUEST_HEADERS")

        if request_url and request_headers:
            return {
                "role": role,
                "identity_request_url": request_url,
                "identity_request_headers": request_headers,
            }

        raise ValueError(
            "Alicloud auth requires VAULT_ALICLOUD_IDENTITY_REQUEST_URL and "
            "VAULT_ALICLOUD_IDENTITY_REQUEST_HEADERS with a pre-signed STS "
            "GetCallerIdentity request."
        )

    def build_login_payload(self) -> dict[str, Any]:
        if self._login_payload is not None:
            return self._login_payload
        return self.resolve_login_payload(self.role)


class CfAuthBackend(VaultAuthBackend):
    method_name = "cf"
    default_mount = "cf"
    _signing_time_format = "%Y-%m-%dT%H:%M:%SZ"

    def __init__(
        self,
        role: str,
        cf_instance_cert: str,
        signing_time: str,
        signature: str,
        mount: str | None = None,
    ) -> None:
        super().__init__(mount=mount)
        self.role = role
        self.cf_instance_cert = cf_instance_cert
        self.signing_time = signing_time
        self.signature = signature

    @classmethod
    def required_env_vars(cls) -> tuple[str, ...]:
        return ("VAULT_CF_ROLE",)

    @classmethod
    def resolve_instance_cert(cls) -> str:
        if cert_value := os.getenv("VAULT_CF_INSTANCE_CERT"):
            return cert_value

        cert_path = os.getenv("CF_INSTANCE_CERT")
        if not cert_path:
            raise ValueError(
                "CF auth requires VAULT_CF_INSTANCE_CERT or CF_INSTANCE_CERT "
                "pointing to the instance identity certificate file."
            )

        cert_file = Path(cert_path)
        if not cert_file.is_file():
            raise ValueError(
                f"CF instance certificate file {cert_path!r} is not readable."
            )

        return cert_file.read_text(encoding="utf-8")

    @classmethod
    def resolve_login_payload(cls, role: str) -> dict[str, str]:
        signing_time = os.getenv("VAULT_CF_SIGNING_TIME")
        signature = os.getenv("VAULT_CF_SIGNATURE")
        cf_instance_cert = cls.resolve_instance_cert()

        if signing_time and signature:
            return {
                "role": role,
                "cf_instance_cert": cf_instance_cert,
                "signing_time": signing_time,
                "signature": signature,
            }

        key_path = os.getenv("CF_INSTANCE_KEY")
        if not key_path:
            raise ValueError(
                "CF auth requires VAULT_CF_SIGNING_TIME and VAULT_CF_SIGNATURE, "
                "or CF_INSTANCE_KEY to sign the login request."
            )

        key_file = Path(key_path)
        if not key_file.is_file():
            raise ValueError(f"CF instance key file {key_path!r} is not readable.")

        return cls.generate_login_payload(
            role,
            cf_instance_cert,
            key_file.read_bytes(),
        )

    @classmethod
    def generate_login_payload(
        cls,
        role: str,
        cf_instance_cert: str,
        private_key_pem: bytes,
        *,
        signing_time: str | None = None,
    ) -> dict[str, str]:
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding, utils
        except ImportError as exc:
            raise ImportError(
                "CF auth requires cryptography to sign login requests. Install with "
                "'pip install pydantic2-settings-vault[cf]' or set "
                "VAULT_CF_SIGNING_TIME and VAULT_CF_SIGNATURE."
            ) from exc

        from datetime import datetime, timezone

        resolved_signing_time = signing_time or datetime.now(timezone.utc).strftime(
            cls._signing_time_format
        )
        to_sign = f"{resolved_signing_time}{cf_instance_cert}{role}"
        digest = hashes.Hash(hashes.SHA256())
        digest.update(to_sign.encode())
        hashed = digest.finalize()

        private_key = serialization.load_pem_private_key(
            private_key_pem,
            password=None,
        )
        signature_bytes = private_key.sign(
            hashed,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            utils.Prehashed(hashes.SHA256()),
        )
        signature = f"v1:{base64.b64encode(signature_bytes).decode()}"

        return {
            "role": role,
            "cf_instance_cert": cf_instance_cert,
            "signing_time": resolved_signing_time,
            "signature": signature,
        }

    def build_login_payload(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "cf_instance_cert": self.cf_instance_cert,
            "signing_time": self.signing_time,
            "signature": self.signature,
        }


class PcfAuthBackend(CfAuthBackend):
    method_name = "pcf"
    default_mount = "pcf"
