# Vault KV engines, paths, and policies

This library reads secrets from HashiCorp Vault KV secrets engines. KV v1 and KV v2 use different HTTP paths and response shapes. pydantic2-settings-vault normalizes logical paths and parses responses based on the configured KV version.

## KV version configuration

Set the default KV version with `VAULT_KV_VERSION`:

| Value | Engine | Default |
| --- | --- | --- |
| `2` | KV secrets engine v2 | yes |
| `1` | KV secrets engine v1 | |

Override per field with `vault_kv_version` in `json_schema_extra`:

```python
DB_PASSWORD: SecretStr = Field(
    ...,
    json_schema_extra={
        "vault_secret_path": "legacy/data/app",
        "vault_secret_key": "password",
        "vault_kv_version": 1,
    },
)
```

`validate_vault_configuration` reports invalid global or per-field KV version values before settings load.

## Path conventions

### KV v2 (default)

Logical path (recommended in field metadata):

```text
secret/myapp/config
```

HTTP API path used by Vault:

```text
secret/data/myapp/config
```

You can still use the full API path (`secret/data/myapp/config`) in `vault_secret_path`; the library leaves it unchanged.

### KV v1

Logical path:

```text
secretv1/myapp/config
```

HTTP API path:

```text
secretv1/myapp/config
```

If a v1 field accidentally uses a v2-style path (`secretv1/data/myapp/config`), the library strips the `data/` segment before the HTTP request.

## Field-mapping patterns

### Group secrets by Vault path

Map several settings fields to the same `vault_secret_path` and different `vault_secret_key` values. The source fetches each unique path once and shares the result across fields.

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
```

### Namespace paths by application and environment

Use mount and path segments that match your Vault layout, for example `secret/prod/myapp/database` or `secret/staging/myapp/database`. Keep production and non-production paths distinct so policies can scope access per environment.

### One secret per sensitive value

For high-sensitivity values with different rotation or access requirements, use separate Vault paths and map each field to its own path. This increases HTTP requests but simplifies least-privilege policies.

## Recommended Vault policies

Grant read access only to the paths your application needs. Examples assume AppRole auth at mount `approle`; adjust auth paths and roles to match your deployment.

### KV v2 read policy

```hcl
path "secret/data/myapp/*" {
  capabilities = ["read"]
}

path "auth/approle/login" {
  capabilities = ["create", "update"]
}
```

### KV v1 read policy

```hcl
path "secretv1/myapp/*" {
  capabilities = ["read"]
}

path "auth/approle/login" {
  capabilities = ["create", "update"]
}
```

### Mixed engines

When one service reads both v1 and v2 mounts, combine path rules:

```hcl
path "secret/data/myapp/*" {
  capabilities = ["read"]
}

path "legacy/myapp/*" {
  capabilities = ["read"]
}
```

### Enterprise namespaces

When using `VAULT_NAMESPACE`, policies are defined inside that namespace. The library sends `X-Vault-Namespace` on authentication and secret reads; policy paths refer to secrets within that namespace.

## Environment variables summary

| Variable | Purpose |
| --- | --- |
| `VAULT_KV_VERSION` | Default KV engine version (`1` or `2`, default `2`) |
| `VAULT_URL` | Vault API base URL |
| `VAULT_NAMESPACE` | Optional Enterprise namespace |
| `VAULT_AUTH_METHOD` | Authentication method (default `approle`) |

See [README.md](../README.md) for authentication configuration.
