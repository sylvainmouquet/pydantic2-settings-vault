# Usage guide

This guide covers how to configure Pydantic settings models, annotate fields for Vault lookups, set environment variables, and prepare Vault policies for pydantic2-settings-vault.

For KV path conventions and policy examples by engine version, see [Vault KV & policies](vault-kv-and-policies.md). For auth method details, see [Authentication](authentication.md). For client tuning, cache, and validation, see [Advanced configuration](advanced-configuration.md).

## Quick start

1. Install the package:

```bash
pip install pydantic2-settings-vault
```

2. Define a settings model with Vault-backed fields and register the settings source:

```python
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource
from pydantic2_settings_vault import VaultConfigSettingsSource


class AppSettings(BaseSettings):
    API_KEY: SecretStr = Field(
        ...,
        json_schema_extra={
            "vault_secret_path": "secret/myapp/config",
            "vault_secret_key": "api_key",
        },
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            VaultConfigSettingsSource(settings_cls=settings_cls),
        )
```

3. Configure Vault authentication (AppRole is the default):

```bash
export VAULT_URL="https://vault.example.com:8200"
export VAULT_ROLE_ID="<role-id>"
export VAULT_SECRET_ID="<secret-id>"
```

4. Write the secret in Vault (KV v2 mount `secret`):

```bash
vault kv put -mount=secret myapp/config api_key="super-secret"
```

5. Load settings:

```python
settings = AppSettings()
print(settings.API_KEY.get_secret_value())
```

## Field annotation patterns

### Opt-in Vault fields

Only fields that include `json_schema_extra` with Vault metadata are fetched from Vault. Other fields behave like normal pydantic-settings fields (environment variables, `.env` files, init kwargs, and so on).

```python
class AppSettings(BaseSettings):
    # Loaded from Vault
    DB_PASSWORD: SecretStr = Field(
        ...,
        json_schema_extra={
            "vault_secret_path": "secret/myapp/database",
            "vault_secret_key": "password",
        },
    )

    # Loaded from environment (e.g. DB_HOST=localhost)
    DB_HOST: str = "localhost"
```

### Required metadata

Every Vault-backed field must include both keys in `json_schema_extra`:

| Key | Description |
| --- | --- |
| `vault_secret_path` | Logical Vault path (KV v2) or full API path. See [Path conventions](vault-kv-and-policies.md#path-conventions). |
| `vault_secret_key` | Key inside the secret payload returned by Vault. |

If either key is missing, settings load fails with a clear error naming the field and the missing metadata.

### Field types

Use `SecretStr` for sensitive values so they are not printed in logs or tracebacks by default:

```python
API_KEY: SecretStr = Field(..., json_schema_extra={...})
```

Non-secret configuration values can use any Pydantic-supported type. Vault returns string values; Pydantic coerces them during validation:

```python
MAX_CONNECTIONS: int = Field(
    ...,
    json_schema_extra={
        "vault_secret_path": "secret/myapp/config",
        "vault_secret_key": "max_connections",
    },
)
```

Store `"100"` in Vault; Pydantic validates and converts it to `int`.

### Group secrets by path

Map several fields to the same `vault_secret_path` with different `vault_secret_key` values. The source fetches each unique path once per settings load:

```python
class AppSettings(BaseSettings):
    DB_HOST: str = Field(
        ...,
        json_schema_extra={
            "vault_secret_path": "secret/myapp/database",
            "vault_secret_key": "host",
        },
    )
    DB_PASSWORD: SecretStr = Field(
        ...,
        json_schema_extra={
            "vault_secret_path": "secret/myapp/database",
            "vault_secret_key": "password",
        },
    )
    DB_PORT: int = Field(
        ...,
        json_schema_extra={
            "vault_secret_path": "secret/myapp/database",
            "vault_secret_key": "port",
        },
    )
```

Write all keys in one Vault secret:

```bash
vault kv put -mount=secret myapp/database host=db.internal port=5432 password="s3cret"
```

### Per-field KV engine version

Set the default KV version globally with `VAULT_KV_VERSION` (`2` by default). Override on individual fields when reading legacy KV v1 mounts:

```python
LEGACY_TOKEN: SecretStr = Field(
    ...,
    json_schema_extra={
        "vault_secret_path": "legacy/myapp/token",
        "vault_secret_key": "value",
        "vault_kv_version": 1,
    },
)
```

### Settings source order

Register `VaultConfigSettingsSource` last in `settings_customise_sources` so explicit init values and environment variables take precedence over Vault:

```python
return (
    init_settings,       # highest priority
    env_settings,
    dotenv_settings,
    file_secret_settings,
    VaultConfigSettingsSource(settings_cls=settings_cls),  # lowest priority
)
```

### Reusable annotation helper

To avoid repeating path metadata, define a small factory in your application:

```python
from typing import Any
from pydantic import Field


def vault_field(path: str, key: str, **field_kwargs: Any):
    return Field(
        ...,
        json_schema_extra={
            "vault_secret_path": path,
            "vault_secret_key": key,
        },
        **field_kwargs,
    )


class AppSettings(BaseSettings):
    API_KEY: SecretStr = vault_field("secret/myapp/config", "api_key")
```

## End-to-end configuration examples

### Local development with AppRole

Run Vault locally (Docker example):

```bash
docker run --cap-add=IPC_LOCK -e 'VAULT_DEV_ROOT_TOKEN=root' -p 8200:8200 hashicorp/vault server -dev
export VAULT_ADDR=http://127.0.0.1:8200
export VAULT_TOKEN=root
```

Enable the KV v2 engine, write a secret, create a read policy, and configure AppRole:

```bash
vault secrets enable -path=secret kv-v2

vault kv put -mount=secret myapp/config api_key="dev-key"

vault policy write myapp-read - <<EOF
path "secret/data/myapp/*" {
  capabilities = ["read"]
}
path "auth/approle/login" {
  capabilities = ["create", "update"]
}
EOF

vault auth enable approle
vault write auth/approle/role/myapp token_policies="myapp-read"
vault write auth/approle/role/myapp/secret-id

export VAULT_ROLE_ID=$(vault read -field=role_id auth/approle/role/myapp/role-id)
export VAULT_SECRET_ID=$(vault write -f -field=secret_id auth/approle/role/myapp/secret-id)
export VAULT_URL=http://127.0.0.1:8200
```

Use a cached settings accessor for repeated lookups in development:

```python
from functools import lru_cache
from threading import Lock

app_settings_lock = Lock()


@lru_cache
def get_app_settings() -> AppSettings:
    with app_settings_lock:
        return AppSettings()  # type: ignore[call-arg]
```

### Kubernetes deployment

Use the Kubernetes auth method and a service-account JWT:

```python
import os

os.environ["VAULT_AUTH_METHOD"] = "kubernetes"
os.environ["VAULT_K8S_ROLE"] = "myapp"
os.environ["VAULT_URL"] = "https://vault.example.com:8200"
# JWT is read from /var/run/secrets/kubernetes.io/serviceaccount/token by default
```

Vault policy for the role should allow read on application secret paths and login on the Kubernetes auth mount. Example:

```hcl
path "secret/data/myapp/*" {
  capabilities = ["read"]
}

path "auth/kubernetes/login" {
  capabilities = ["create", "update"]
}
```

Bind the Kubernetes auth role to the pod service account:

```bash
vault write auth/kubernetes/role/myapp \
  bound_service_account_names=myapp \
  bound_service_account_namespaces=production \
  policies=myapp-read \
  ttl=1h
```

### Production startup with validation

Validate configuration before serving traffic. Use a dedicated settings class or factory when you need production client tuning:

```python
from pydantic2_settings_vault import (
    VaultClientConfig,
    VaultConfigSettingsSource,
    validate_vault_configuration,
)


class ProductionAppSettings(AppSettings):
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            VaultConfigSettingsSource(
                settings_cls=settings_cls,
                client_config=VaultClientConfig.for_production(),
                cache_enabled=True,
                cache_ttl_seconds=300,
            ),
        )


def bootstrap_settings() -> ProductionAppSettings:
    validate_vault_configuration(
        ProductionAppSettings,
        check_auth=True,  # dry-run login against Vault
    ).raise_if_invalid()

    return ProductionAppSettings()  # type: ignore[call-arg]
```

Run the same validation in CI without loading secrets:

```python
# Fails fast on missing env vars or incomplete field metadata; no secret fetch
validate_vault_configuration(AppSettings).raise_if_invalid()
```

### Mixed configuration sources

Combine Vault secrets with environment-driven non-secret settings:

```python
from pydantic_settings import SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MYAPP_")

    # From environment: MYAPP_ENV=production
    ENV: str = "development"

    # From Vault
    API_KEY: SecretStr = Field(
        ...,
        json_schema_extra={
            "vault_secret_path": "secret/myapp/config",
            "vault_secret_key": "api_key",
        },
    )
```

Path layout can include the environment segment for policy scoping:

```python
vault_secret_path=f"secret/{env}/myapp/config"  # set at class definition or via factory
```

Prefer distinct paths per environment (`secret/prod/...`, `secret/staging/...`) rather than sharing production secrets across environments.

## Environment variables

### Common variables (all auth methods)

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `VAULT_URL` | No | `http://127.0.0.1:8200` | Vault API base URL |
| `VAULT_AUTH_METHOD` | No | `approle` | Authentication backend to use |
| `VAULT_AUTH_MOUNT` | No | method name | Auth mount path override (e.g. `kubernetes` → `auth/kubernetes/login`) |
| `VAULT_NAMESPACE` | No | — | HashiCorp Vault Enterprise namespace (`X-Vault-Namespace` header) |
| `VAULT_KV_VERSION` | No | `2` | Default KV engine version (`1` or `2`) |

### AppRole (default)

| Variable | Required |
| --- | --- |
| `VAULT_ROLE_ID` | Yes |
| `VAULT_SECRET_ID` | Yes |

### Other auth methods

Token, Kubernetes, AWS, GCP, Azure, JWT, OIDC, Cert, LDAP, OCI, Userpass, GitHub, Okta, Kerberos, RADIUS, Alicloud, CF, and PCF each require method-specific variables. See the [Authentication](authentication.md) guide for the full reference.

### Optional client tuning

`VaultClientConfig` is passed to `VaultConfigSettingsSource` in code, not via environment variables. Presets:

| Preset | Timeout | Concurrency | Retries | Backoff |
| --- | ---: | ---: | ---: | --- |
| `VaultClientConfig.for_local()` | 60s | 3 | 3 | 0.2s → 1.0s |
| `VaultClientConfig.for_ci()` | 15s | 5 | 2 | 0.05s → 0.2s |
| `VaultClientConfig.for_production()` | 30s | 10 | 5 | 0.1s → 2.0s |

## Recommended Vault policies

Grant the narrowest read access required. Examples assume AppRole at mount `approle`; adjust auth paths for your method.

### KV v2 application policy

```hcl
# Read application secrets only
path "secret/data/myapp/*" {
  capabilities = ["read"]
}

# Allow AppRole login
path "auth/approle/login" {
  capabilities = ["create", "update"]
}
```

Create and attach the policy:

```bash
vault policy write myapp-read - <<EOF
path "secret/data/myapp/*" {
  capabilities = ["read"]
}
path "auth/approle/login" {
  capabilities = ["create", "update"]
}
EOF

vault write auth/approle/role/myapp token_policies="myapp-read"
```

### AppRole setup checklist

1. Enable AppRole: `vault auth enable approle`
2. Write a policy with read on secret paths and login on `auth/approle/login`
3. Create a role: `vault write auth/approle/role/myapp token_policies="myapp-read"`
4. Distribute `role_id` (can be wrapped) and generate `secret_id` per deployment
5. Set `VAULT_ROLE_ID`, `VAULT_SECRET_ID`, and `VAULT_URL` in the runtime environment

### Enterprise namespaces

When using `VAULT_NAMESPACE`, define policies inside that namespace. The library sends `X-Vault-Namespace` on authentication and secret reads automatically.

### KV v1 and mixed engines

See [vault-kv-and-policies.md](vault-kv-and-policies.md) for KV v1 paths, mixed-engine policies, and field-mapping patterns.

## Troubleshooting

| Symptom | Likely cause | Action |
| --- | --- | --- |
| `Missing required Vault environment variables` | Auth credentials not set | Set method-specific vars; run `validate_vault_configuration` |
| `Vault metadata for settings field 'X' is incomplete` | Missing path or key in `json_schema_extra` | Add both `vault_secret_path` and `vault_secret_key` |
| `Vault secret key 'X' ... was not found at Vault path 'Y'` | Key missing in Vault payload | Fix secret content or `vault_secret_key` name |
| Pydantic `ValidationError` after Vault fetch | Type coercion failed | Store a value compatible with the field type in Vault |
| HTTP 403 on secret read | Policy too narrow | Extend policy to cover `secret/data/<path>` (KV v2) |

Sensitive values are never included in log messages or exception text.

## Related documentation

- [Authentication](authentication.md) — all supported Vault auth methods
- [Advanced configuration](advanced-configuration.md) — client controls, cache, validation API
- [Vault KV & policies](vault-kv-and-policies.md) — KV v1/v2 paths, policies, field-mapping patterns
