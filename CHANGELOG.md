# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

### Added

- `VaultClientConfig` to tune Vault HTTP timeouts, retry backoff, and secret-fetch concurrency on `VaultConfigSettingsSource`, with `for_local()`, `for_ci()`, and `for_production()` presets.
- Optional in-memory Vault secret cache via `VaultConfigSettingsSource(cache_enabled=True, cache_ttl_seconds=...)`, or an explicit `VaultSecretCache` instance passed as `secret_cache`. Cache is disabled by default.
- `VaultSecretCache` public type for shared, TTL-based secret caching across repeated settings loads.
- KV secrets engine version selection via `VAULT_KV_VERSION` (default `2`) and per-field `vault_kv_version` metadata.
- KV path normalization for v1 and v2 (`secret/test` → `secret/data/test` for KV v2 reads).
- Vault KV policies, path conventions, and field-mapping guidance in `docs/vault-kv-and-policies.md`.
- `just` recipes: `format`, `coverage`, and `check`; development docs in `README.md`, `AGENTS.md`, `SPECS.md`, and `docs/development.md`.
- Pluggable Vault authentication via `VAULT_AUTH_METHOD` with Phase 1 backends: token, kubernetes, aws, gcp, and azure (AppRole remains the default).
- Configurable auth mount path via `VAULT_AUTH_MOUNT`.
- Optional dependencies for cloud credential resolution: `[aws]`, `[gcp]`, `[azure]`, `[oci]`, and `[cloud]`.
- Unit tests for auth backends and token-auth integration tests against Vault.
- Phase 2 Vault auth backends: jwt, oidc, cert, ldap, and oci.
- Optional `[oci]` dependency group for OCI request signing.
- Phase 3 Vault auth backends: userpass, github, okta, kerberos, radius, alicloud, cf, and pcf.
- Optional `[cf]` dependency group for Cloud Foundry login signature generation.
- Shared Vault HTTP mock helpers and unit tests for `InternalHttpVault` and `VaultConfigSettingsSource` failure modes (missing keys, auth errors, HTTP errors, network failures).

### Changed

- `InternalHttpVault.get_secrets` parses KV v1 and v2 responses and normalizes paths before HTTP reads.
- `validate_vault_configuration` validates `VAULT_KV_VERSION` and per-field `vault_kv_version` values.
- `InternalHttpVault` delegates authentication to `VaultAuthBackend` instead of hard-coded AppRole login.
- `validate_vault_configuration` validates method-specific environment variables and supports dry-run auth for all supported methods.
- `InternalHttpVault` supports mTLS client-certificate login for cert auth backends.
- `InternalHttpVault` merges backend-specific login headers (for example Kerberos `Authorization: Negotiate`).

### Fixed

### Removed
