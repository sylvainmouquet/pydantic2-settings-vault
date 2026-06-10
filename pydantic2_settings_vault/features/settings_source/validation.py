import asyncio
import concurrent.futures
import os
from dataclasses import dataclass, field
from typing import Any

from pydantic_settings import BaseSettings

from pydantic2_settings_vault.features.authentication.registry import (
    get_auth_backend_from_env,
    get_required_env_vars_for_method,
    resolve_auth_method,
)
from pydantic2_settings_vault.shared.infrastructure.vault_http import InternalHttpVault

VAULT_METADATA_KEYS: tuple[str, str] = ("vault_secret_path", "vault_secret_key")


@dataclass(frozen=True)
class VaultValidationIssue:
    code: str
    message: str
    field_name: str | None = None


@dataclass
class VaultValidationResult:
    errors: list[VaultValidationIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors

    def raise_if_invalid(self) -> None:
        if not self.valid:
            messages = "; ".join(issue.message for issue in self.errors)
            raise ValueError(messages)


def _collect_missing_env_vars(
    env_vars: tuple[str, ...] | None = None,
) -> list[VaultValidationIssue]:
    issues: list[VaultValidationIssue] = []
    required_env_vars = env_vars or get_required_env_vars_for_method()
    missing_env_vars = [
        env_var for env_var in required_env_vars if not os.getenv(env_var)
    ]

    if missing_env_vars:
        missing_env_vars_text = ", ".join(missing_env_vars)
        auth_method = resolve_auth_method()
        issues.append(
            VaultValidationIssue(
                code="missing_env_vars",
                message=(
                    "Missing required Vault environment variables: "
                    f"{missing_env_vars_text}. Configure {auth_method} auth credentials "
                    "before loading Vault-backed settings."
                ),
            )
        )

    return issues


def _iter_vault_backed_fields(
    settings_cls: type[BaseSettings],
) -> list[tuple[str, dict[str, Any]]]:
    vault_backed_fields: list[tuple[str, dict[str, Any]]] = []

    for field_name, field_info in settings_cls.model_fields.items():
        if not field_info.json_schema_extra:
            continue

        field_metadata = field_info.json_schema_extra
        if isinstance(field_metadata, dict):
            vault_backed_fields.append((field_name, field_metadata))

    return vault_backed_fields


def _collect_field_metadata_issues(
    settings_cls: type[BaseSettings],
) -> list[VaultValidationIssue]:
    issues: list[VaultValidationIssue] = []

    for field_name, field_metadata in _iter_vault_backed_fields(settings_cls):
        missing_metadata = [
            metadata_key
            for metadata_key in VAULT_METADATA_KEYS
            if not field_metadata.get(metadata_key)
        ]

        if missing_metadata:
            missing_metadata_text = ", ".join(missing_metadata)
            issues.append(
                VaultValidationIssue(
                    code="incomplete_field_metadata",
                    message=(
                        "Vault metadata for settings field "
                        f"'{field_name}' is incomplete. Missing: {missing_metadata_text}."
                    ),
                    field_name=field_name,
                )
            )

    return issues


def _run_vault_auth_check(
    vault_url: str,
    vault_namespace: str | None,
) -> VaultValidationIssue | None:
    async def _authenticate() -> None:
        async with InternalHttpVault(
            url=vault_url,
            namespace=vault_namespace,
            auth_backend=get_auth_backend_from_env(),
        ):
            return

    def run_async_method() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_authenticate())
        finally:
            loop.close()

    try:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            executor.submit(run_async_method).result()
    except Exception as exc:
        auth_method = resolve_auth_method()
        return VaultValidationIssue(
            code="auth_failed",
            message=f"Vault {auth_method} authentication check failed: {exc}",
        )

    return None


def validate_vault_configuration(
    settings_cls: type[BaseSettings],
    *,
    check_auth: bool = False,
    vault_url: str | None = None,
    vault_namespace: str | None = None,
) -> VaultValidationResult:
    """Validate Vault environment variables and field metadata for a settings model.

    When ``check_auth`` is enabled, performs a dry-run authentication against Vault
    using the configured auth method without fetching secrets.
    """
    result = VaultValidationResult()
    has_vault_backed_fields = bool(_iter_vault_backed_fields(settings_cls))

    if has_vault_backed_fields:
        result.errors.extend(_collect_missing_env_vars())
    result.errors.extend(_collect_field_metadata_issues(settings_cls))

    if not check_auth or not result.valid or not has_vault_backed_fields:
        return result

    resolved_vault_url = vault_url or os.getenv("VAULT_URL", "http://127.0.0.1:8200")
    resolved_vault_namespace = (
        vault_namespace if vault_namespace is not None else os.getenv("VAULT_NAMESPACE")
    )

    auth_issue = _run_vault_auth_check(
        vault_url=resolved_vault_url,
        vault_namespace=resolved_vault_namespace,
    )
    if auth_issue is not None:
        result.errors.append(auth_issue)

    return result
