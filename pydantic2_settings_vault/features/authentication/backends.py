from __future__ import annotations

import base64
import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar
from urllib.parse import urlparse

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

    @abstractmethod
    def build_login_payload(self) -> dict[str, str]:
        """Build the JSON body for POST ``/v1/auth/<mount>/login``."""

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

    def build_login_payload(self) -> dict[str, str]:
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

    def build_login_payload(self) -> dict[str, str]:
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

    def build_login_payload(self) -> dict[str, str]:
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

    def build_login_payload(self) -> dict[str, str]:
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

    def build_login_payload(self) -> dict[str, str]:
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

    def build_login_payload(self) -> dict[str, str]:
        return {
            "role": self.role,
            "jwt": self.jwt.get_secret_value(),
        }
