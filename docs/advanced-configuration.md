# Advanced configuration

## Vault client controls

Tune HTTP timeouts, retry behavior, and fetch concurrency via `VaultClientConfig`:

```python
from pydantic2_settings_vault import VaultClientConfig, VaultConfigSettingsSource

client_config = VaultClientConfig(
    request_timeout=30.0,       # seconds per Vault HTTP request
    max_concurrent_requests=5,  # parallel secret fetches per settings load
    retry_max_attempts=5,       # retries on transient failures
    retry_min_delay=0.1,        # initial backoff (seconds)
    retry_max_delay=2.0,        # maximum backoff (seconds)
)

VaultConfigSettingsSource(
    settings_cls=settings_cls,
    client_config=client_config,
)
```

Recommended presets for common environments:

| Environment | Preset | Timeout | Concurrency | Retries | Backoff (min → max) |
| --- | --- | ---: | ---: | ---: | --- |
| Local development | `VaultClientConfig.for_local()` | 60s | 3 | 3 | 0.2s → 1.0s |
| CI pipelines | `VaultClientConfig.for_ci()` | 15s | 5 | 2 | 0.05s → 0.2s |
| Production | `VaultClientConfig.for_production()` | 30s | 10 | 5 | 0.1s → 2.0s |

Use local presets when Vault runs in Docker or on a laptop (slower startup, fewer parallel calls). Use CI presets to fail fast when Vault is unavailable. Use production presets for resilient secret loading under higher load.

## Secret cache

Vault path fetches are deduplicated within a single settings load. To avoid repeated Vault calls across multiple settings initializations, opt in to the in-memory cache (disabled by default):

```python
from pydantic2_settings_vault import VaultConfigSettingsSource, VaultSecretCache

# Shared module-level cache with a 5-minute TTL
VaultConfigSettingsSource(
    settings_cls=settings_cls,
    cache_enabled=True,
    cache_ttl_seconds=300,
)

# Or pass an explicit cache instance shared across sources
secret_cache = VaultSecretCache(ttl_seconds=300)
VaultConfigSettingsSource(settings_cls=settings_cls, secret_cache=secret_cache)
```

Cached values are still validated by Pydantic when settings are constructed.

## Pre-startup validation

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

## Related documentation

- [Usage guide](usage.md) — field annotations and end-to-end examples
- [Authentication](authentication.md) — auth methods and environment variables
