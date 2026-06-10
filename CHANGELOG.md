# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

### Added

- Pluggable Vault authentication via `VAULT_AUTH_METHOD` with Phase 1 backends: token, kubernetes, aws, gcp, and azure (AppRole remains the default).
- Configurable auth mount path via `VAULT_AUTH_MOUNT`.
- Optional dependencies for cloud credential resolution: `[aws]`, `[gcp]`, `[azure]`, and `[cloud]`.
- Unit tests for auth backends and token-auth integration tests against Vault.

### Changed

- `InternalHttpVault` delegates authentication to `VaultAuthBackend` instead of hard-coded AppRole login.
- `validate_vault_configuration` validates method-specific environment variables and supports dry-run auth for all Phase 1 methods.

### Fixed

### Removed
