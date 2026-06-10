# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

### Added

- `just` recipes: `format`, `coverage`, and `check`; development docs in `README.md`, `AGENTS.md`, `SPECS.md`, and `docs/development.md`.
- Pluggable Vault authentication via `VAULT_AUTH_METHOD` with Phase 1 backends: token, kubernetes, aws, gcp, and azure (AppRole remains the default).
- Configurable auth mount path via `VAULT_AUTH_MOUNT`.
- Optional dependencies for cloud credential resolution: `[aws]`, `[gcp]`, `[azure]`, `[oci]`, and `[cloud]`.
- Unit tests for auth backends and token-auth integration tests against Vault.
- Phase 2 Vault auth backends: jwt, oidc, cert, ldap, and oci.
- Optional `[oci]` dependency group for OCI request signing.

### Changed

- `InternalHttpVault` delegates authentication to `VaultAuthBackend` instead of hard-coded AppRole login.
- `validate_vault_configuration` validates method-specific environment variables and supports dry-run auth for all supported methods.
- `InternalHttpVault` supports mTLS client-certificate login for cert auth backends.

### Fixed

### Removed
