![license](https://img.shields.io/pypi/l/pydantic2-settings-vault?style=for-the-badge) ![python version](https://img.shields.io/pypi/pyversions/pydantic2-settings-vault?style=for-the-badge) [![version](https://img.shields.io/pypi/v/pydantic2-settings-vault?style=for-the-badge)](https://pypi.org/project/pydantic2-settings-vault/) [![](https://img.shields.io/pypi/dm/pydantic2-settings-vault?style=for-the-badge)](https://pypi.org/project/pydantic2-settings-vault/)


# pydantic2-settings-vault

Simple extension of [pydantic_settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) to collect secrets in [HashiCorp Vault](https://www.hashicorp.com/fr/products/vault) OpenSource (OSS) and Enterprise

__pydantic2-settings-vault__ is a extension for Pydantic Settings that enables secure configuration management by integrating with __HashiCorp Vault__. This library supports both the open-source (OSS) and Enterprise versions of Vault, providing a seamless way to retrieve and manage secrets within your Pydantic-based applications. By leveraging Vault's robust security features, __pydantic2-settings-vault__ allows developers to easily incorporate secure secret management practices into their Python projects, enhancing overall application security and simplifying the handling of sensitive configuration data.

  - [Installation](#installation)
  - [Demonstration](#demonstration)
  - [License](#license)
  - [Contact](#contact)

## Installation

pip

```bash
pip install pydantic2-settings-vault
```
poetry

```bash
poetry add pydantic2-settings-vault
```

uv

```bash
uv add pydantic2-settings-vault
```

### Getting started

Create a class __AppSettings__ that inherit of __BaseSettings__ . 

Create a field for each vault secret. 

ex: 
```python
MY_SECRET: SecretStr = Field(
        ...,
        json_schema_extra={
            "vault_secret_path": "secret/data/test",
            "vault_secret_key": "FOO",  # pragma: allowlist secret
        },
    )
```

#### Full example
```python
from functools import lru_cache
from threading import Lock
from typing import Tuple, Type
from pydantic import Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
)
from pydantic2_settings_vault import VaultConfigSettingsSource

class AppSettings(BaseSettings):

    MY_SECRET: SecretStr = Field(
        ...,
        json_schema_extra={
            "vault_secret_path": "secret/data/test",
            "vault_secret_key": "FOO",  # pragma: allowlist secret
        },
    )
    
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            VaultConfigSettingsSource(settings_cls=settings_cls), #   add this line
        )

# The connection to Vault is done via HTTPS with AppRole authentication (default)
import os
os.environ['VAULT_URL'] = "<configure it>"
os.environ['VAULT_ROLE_ID'] = "<configure it>"
os.environ['VAULT_SECRET_ID'] = "<configure it>"

# Only with Enterprise edition
os.environ['VAULT_NAMESPACE'] = "<configure it>"
```

#### Authentication methods

Select the auth backend with `VAULT_AUTH_METHOD` (default: `approle`). Override the mount path with optional `VAULT_AUTH_MOUNT`.

| Method | `VAULT_AUTH_METHOD` | Required environment variables |
| --- | --- | --- |
| AppRole (default) | `approle` | `VAULT_ROLE_ID`, `VAULT_SECRET_ID` |
| Token | `token` | `VAULT_TOKEN` |
| Kubernetes | `kubernetes` | `VAULT_K8S_ROLE`, plus `VAULT_K8S_JWT` or service-account token file |
| AWS | `aws` | `VAULT_AWS_ROLE`, plus signed STS request env vars or `botocore` credentials |
| GCP | `gcp` | `VAULT_GCP_ROLE`, plus `VAULT_GCP_JWT` or `GOOGLE_APPLICATION_CREDENTIALS` |
| Azure | `azure` | `VAULT_AZURE_ROLE`, plus `VAULT_AZURE_JWT` or Azure managed identity |

Common variables for every method:

- `VAULT_URL` — Vault API address (default: `http://127.0.0.1:8200`)
- `VAULT_NAMESPACE` — optional Enterprise namespace
- `VAULT_AUTH_MOUNT` — optional auth mount override (defaults: `approle`, `token`, `kubernetes`, `aws`, `gcp`, `azure`)

**Token auth** uses a pre-issued token directly; no login call is made.

**Kubernetes auth** reads the service-account JWT from `VAULT_K8S_JWT` or, by default, `/var/run/secrets/kubernetes.io/serviceaccount/token`.

**AWS auth** signs an STS `GetCallerIdentity` request with instance profile, environment keys, or web identity when `botocore` is installed (`pip install pydantic2-settings-vault[aws]`). You can also supply a pre-signed request via `VAULT_AWS_IAM_REQUEST_URL`, `VAULT_AWS_IAM_REQUEST_BODY`, and `VAULT_AWS_IAM_REQUEST_HEADERS`.

**GCP auth** obtains a service-account JWT from `google-auth` when installed (`pip install pydantic2-settings-vault[gcp]`), or from `VAULT_GCP_JWT`.

**Azure auth** obtains a managed-identity or service-principal token from `azure-identity` when installed (`pip install pydantic2-settings-vault[azure]`), or from `VAULT_AZURE_JWT`.

Example token auth:

```python
os.environ["VAULT_AUTH_METHOD"] = "token"
os.environ["VAULT_TOKEN"] = "<configure it>"
os.environ["VAULT_URL"] = "<configure it>"
```

Example Kubernetes auth:

```python
os.environ["VAULT_AUTH_METHOD"] = "kubernetes"
os.environ["VAULT_K8S_ROLE"] = "<vault role>"
os.environ["VAULT_URL"] = "<configure it>"
# Optional: os.environ["VAULT_K8S_JWT"] = "<service account jwt>"
# Optional: os.environ["VAULT_AUTH_MOUNT"] = "kubernetes"
```

### Pre-startup validation

Validate Vault environment variables and field metadata before loading settings:

```python
from pydantic2_settings_vault import validate_vault_configuration

result = validate_vault_configuration(AppSettings)
if not result.valid:
    for issue in result.errors:
        print(f"{issue.code}: {issue.message}")

# Or fail fast during application startup:
validate_vault_configuration(AppSettings).raise_if_invalid()

# Optionally verify Vault authentication without fetching secrets:
validate_vault_configuration(AppSettings, check_auth=True).raise_if_invalid()
```

### Usage
app_settings_lock = Lock()

@lru_cache
def get_app_settings() -> AppSettings:
    with app_settings_lock:
        return AppSettings()  # type: ignore
```

### Internal interactions:
```mermaid
sequenceDiagram
    participant A as Your Application
    participant B as BaseSettings
    participant V as Vault
    note over A,B: 1. Retrieve settings
    A->>B: get_app_settings()
    note over B: 2. Collect secrets paths
    B->>B: foreach fields, get the secret path and keep unique value
    note over B,V: 3. HTTPS Asynchronously fetch secrets by path from Vault
    B->>V: get_secrets(secrets/data/<A>)
    B->>V: get_secrets(secrets/data/<B>)
    note over V,B: 4. Vault returns secrets
    V->>B: return secrets for secrets/data/<A>
    V->>B: return secrets for secrets/data/<B>
    note over B: 5. Fill fields with secrets values
    B->>B: SECRET_ONE => secrets/data/<A>[SECRET_ONE] <br> SECRET_TWO => secrets/data/<A>[SECRET_TWO] <br> SECRET_THREE => secrets/data/<B>[SECRET_THREE]
    note over B,A: 6. Return settings
    B->>A: settings with variables and secrets
```



## License

Pydantic2-Settings-Vault is released under the MIT License. See the [LICENSE](LICENSE) file for more details.

## Contact

For questions, suggestions, or issues related to Pydantic2-Settings-Vault, please open an issue on the GitHub repository.

