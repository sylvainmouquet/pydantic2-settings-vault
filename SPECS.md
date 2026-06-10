# pydantic2-settings-vault — Product Specification

Python package for managing app secrets in Pydantic v2 settings from HashiCorp Vault.

---

## High impact, relatively simple

### 1. Vault Authentication (AppRole)

**Status:** Done

Enables secure authentication to Vault using the AppRole method. Reads credentials from environment variables and establishes an HTTP session for secret lookups.

- [x] Reads `VAULT_URL`, `VAULT_ROLE_ID`, `VAULT_SECRET_ID` from environment variables
- [x] Reads optional `VAULT_NAMESPACE` for HashiCorp Vault Enterprise deployments (see feature 15)
- [x] Authenticates via POST to `/v1/auth/approle/login`
- [x] Stores received token for future secret requests
- [x] Handles errors and closes the HTTP session safely

**Key files:** `pydantic2_settings_vault/__init__.py`

---

### 2. Pydantic field vault mapping

**Status:** Done

Discovers which Pydantic fields require a Vault secret and maps them to the correct path/key in Vault using Pydantic field metadata.

- [x] Scans `model_fields` for `json_schema_extra["vault_secret_path"]` and `json_schema_extra["vault_secret_key"]`
- [x] Builds the list of secrets to request from Vault
- [x] Groups fields by Vault path for efficient querying

**Key files:** `pydantic2_settings_vault/__init__.py`

---

### 3. Concurrent secret fetching

**Status:** Done

Fetches all needed secrets in parallel using `asyncio.gather` and a custom concurrency limiter.

- [x] Concurrency controlled by `concurrency_limiter` (default max 5 concurrent requests, configurable via `VaultClientConfig`)
- [x] Async workflows wrapped to run safely inside a thread executor
- [x] All Vault requests are retried using the `reattempt` decorator in case of transient failure (configurable via `VaultClientConfig`)

**Key files:** `pydantic2_settings_vault/features/settings_source/source.py`, `pydantic2_settings_vault/shared/infrastructure/vault_client_config.py`

---

### 4. Error handling & logging

**Status:** Done

Produces actionable logs on error, and makes failures explicit to callers. Errors are reported for missing keys, authentication failures, and network issues.

- [x] Uses Python's `logging` framework for logs
- [x] Logs missing secret keys and HTTP error responses
- [x] Raises exceptions for fatal errors so app configuration fails fast when secrets are missing

**Key files:** `pydantic2_settings_vault/__init__.py`

---

### 5. Integration with pydantic-settings v2

**Status:** Done

Acts as a drop-in settings source for Pydantic v2. Users just add the source, annotate the fields, and secrets are loaded from Vault securely at runtime.

- [x] Implements `PydanticBaseSettingsSource` interface
- [x] Supports synchronous or async field value computation
- [x] Handles model initialization contract for Pydantic

**Key files:** `pydantic2_settings_vault/__init__.py`

---

## Medium impact — broadens scope

### 6. Support all HashiCorp Vault auth methods

**Status:** Done

Extend authentication beyond AppRole so applications can use any [built-in Vault auth method](https://developer.hashicorp.com/vault/docs/auth) appropriate to their runtime. Introduce a pluggable auth backend selected via configuration (for example `VAULT_AUTH_METHOD` and method-specific environment variables), with support for custom mount paths (`auth/<mount>`).

**Phase 1 — machine and cloud-native (highest priority for settings loading)**

- [x] **Token** — authenticate with a pre-issued `VAULT_TOKEN` (no login call; token used directly on secret requests)
- [x] **Kubernetes** — service-account JWT login via `/v1/auth/<mount>/login`
- [x] **AWS** — IAM credentials (instance profile, env keys, or web identity) via `/v1/auth/<mount>/login`
- [x] **GCP** — service-account JWT via `/v1/auth/<mount>/login`
- [x] **Azure** — managed identity or service principal via `/v1/auth/<mount>/login`

**Phase 2 — workload identity and certificates**

- [x] **JWT** — generic JWT/OIDC bearer login
- [x] **OIDC** — OIDC provider login (including role-based claims)
- [x] **Cert** — TLS client-certificate authentication
- [x] **LDAP** — bind DN and password login
- [x] **OCI** — Oracle Cloud instance principal or API key login

**Phase 3 — human and legacy integrations**

- [x] **Userpass** — username and password login
- [x] **GitHub** — GitHub personal access token login
- [x] **Okta** — Okta username and password login
- [x] **Kerberos** — SPNEGO/GSSAPI login
- [x] **RADIUS** — RADIUS username and password login
- [x] **Alicloud** — Alibaba Cloud RAM credential login
- [x] **CF** — Cloud Foundry instance credential login
- [x] **PCF** — legacy PCF instance credential login (if still required by deployments)

**Cross-cutting requirements**

- [x] Shared `VaultAuthBackend` protocol used by `InternalHttpVault` instead of hard-coded AppRole login
- [x] Configurable auth mount path per method (Vault allows multiple mounts of the same type)
- [x] Method-specific required env vars validated by `validate_vault_configuration`
- [x] Dry-run auth check (`check_auth=True`) works for every supported method
- [x] Document per-method env vars, mount paths, and recommended deployment patterns in `README.md`

**Potential files:** `pydantic2_settings_vault/features/authentication/`, `pydantic2_settings_vault/shared/infrastructure/vault_http.py`, `pydantic2_settings_vault/features/settings_source/validation.py`, `test/features/authentication/`, `README.md`

**Key files:** `pydantic2_settings_vault/features/authentication/backends.py`, `pydantic2_settings_vault/features/authentication/registry.py`, `pydantic2_settings_vault/shared/infrastructure/vault_http.py`, `pydantic2_settings_vault/features/settings_source/validation.py`, `test/features/authentication/test_backends.py`, `README.md`

### 7. Improve testing and mocking

**Status:** Done

Add comprehensive automated tests that cover Vault API responses, field mapping, authentication, and failure modes.

- [x] Add tests for Vault HTTP authentication and secret fetch logic
- [x] Mock Vault API responses for success and error scenarios
- [x] Cover missing key, network failure, and authentication failure behavior

**Key files:** `test/features/shared/vault_mocks.py`, `test/features/shared/test_vault_http.py`, `test/features/settings_source/test_source.py`, `test/features/authentication/test_backends.py`

### 8. Usage documentation

**Status:** Done

Provide practical usage examples for configuring settings models, annotating fields, and preparing Vault policies.

- [x] Document field annotation patterns
- [x] Add end-to-end configuration examples
- [x] Explain expected Vault policies and environment variables

**Key files:** `README.md`, `docs/usage.md`, `docs/vault-kv-and-policies.md`

### 9. Configurable Vault client controls

**Status:** Done

Let applications tune Vault request behavior for different runtime environments without modifying package internals.

- [x] Add configurable request timeout values
- [x] Add configurable retry attempts and retry delay strategy
- [x] Expose concurrency limit as a settings-source option
- [x] Document recommended defaults for local, CI, and production usage

**Key files:** `pydantic2_settings_vault/shared/infrastructure/vault_client_config.py`, `pydantic2_settings_vault/features/settings_source/source.py`, `pydantic2_settings_vault/shared/infrastructure/vault_http.py`, `README.md`

### 10. Secret cache and duplicate request reduction

**Status:** Done

Reduce repeated Vault calls when multiple fields reference the same path/key or when settings are initialized repeatedly in short-lived application flows.

- [x] Deduplicate requests for identical Vault path/key pairs during one settings load
- [x] Add optional in-memory cache with a configurable TTL
- [x] Keep cache disabled by default unless the caller opts in
- [x] Add tests proving cached values do not bypass Pydantic validation

**Key files:** `pydantic2_settings_vault/features/settings_source/cache.py`, `pydantic2_settings_vault/features/settings_source/source.py`, `test/features/settings_source/test_cache.py`

---

## Polish & UX

### 11. Developer-facing diagnostics

**Status:** Done

Improve error messages and logs so setup issues are easier to understand during local development and deployment.

- [x] Clarify missing environment variable errors
- [x] Include Vault path/key context in safe error messages
- [x] Keep sensitive values out of logs and exceptions

**Key files:** `pydantic2_settings_vault/features/settings_source/source.py`, `pydantic2_settings_vault/shared/infrastructure/vault_http.py`, `test/features/settings_source/test_settings.py`

### 12. Configuration validation helper

**Status:** Done

Provide a lightweight way to validate Vault connectivity, authentication, and field metadata before an application starts serving traffic.

- [x] Add a helper that checks required Vault environment variables
- [x] Validate that mapped fields include both path and key metadata
- [x] Optionally perform a dry-run Vault authentication check
- [x] Return structured validation errors suitable for CI or startup checks

**Key files:** `pydantic2_settings_vault/features/settings_source/validation.py`, `pydantic2_settings_vault/__init__.py`, `test/features/settings_source/test_validation.py`, `README.md`

---

## New Opportunities

### 13. Advanced HashiCorp Vault support

**Status:** Done

Deepen HashiCorp Vault integration so the library covers more real-world deployment patterns without adding other secret backends. Authentication method coverage is tracked in feature 6.

- [x] Support KV engine version selection and path conventions
- [x] Document recommended Vault policies and field-mapping patterns

**Key files:** `pydantic2_settings_vault/shared/infrastructure/kv_paths.py`, `pydantic2_settings_vault/shared/infrastructure/vault_http.py`, `pydantic2_settings_vault/features/settings_source/source.py`, `pydantic2_settings_vault/features/settings_source/validation.py`, `test/features/shared/test_kv_paths.py`, `test/features/settings_source/test_settings.py`, `docs/vault-kv-and-policies.md`, `README.md`

### 14. Vault token lifecycle management

**Status:** Planned (Long Term)

Support long-running applications that need to keep Vault authentication healthy after initial settings load.

- [ ] Track token TTL and renewable status from Vault authentication responses
- [ ] Explore background token renewal for long-lived processes
- [ ] Define failure behavior when renewal is rejected or expires
- [ ] Document when renewal is useful versus when one-time startup loading is enough

**Potential files:** `pydantic2_settings_vault/__init__.py`, `pydantic2_settings_vault/auth/`

### 15. HashiCorp Vault Enterprise support

**Status:** Done

Support [HashiCorp Vault Enterprise](https://www.hashicorp.com/products/vault) deployments alongside Vault OSS. Enterprise-specific behavior is opt-in via configuration so OSS users are unaffected.

- [x] Read optional `VAULT_NAMESPACE` from environment variables
- [x] Send `X-Vault-Namespace` header on AppRole authentication requests
- [x] Send `X-Vault-Namespace` header on secret read requests
- [x] Accept `vault_namespace` override in `validate_vault_configuration`
- [ ] Add automated tests for namespace header behavior
- [ ] Document OSS vs Enterprise setup (`VAULT_NAMESPACE`) in `README.md`

**Key files:** `pydantic2_settings_vault/shared/infrastructure/vault_http.py`, `pydantic2_settings_vault/features/settings_source/source.py`, `pydantic2_settings_vault/features/settings_source/validation.py`, `README.md`

---

## Recommended Roadmap

### Next Release

- [ ] Test suite for Vault HTTP logic
- [ ] Documentation: usage and advanced examples
- [ ] Configurable timeouts, retries, and concurrency limits
- [ ] Developer-facing diagnostics for setup failures

### Following Release

- [ ] Optional secret cache and duplicate request reduction
- [ ] Configuration validation helper
- [ ] All HashiCorp Vault auth methods (feature 6, phased rollout)

---

## Architecture notes

- Supported Python versions: 3.10, 3.11, 3.12, 3.13, and 3.14 (CI matrix); local development defaults to 3.14
- Task runner: [Just](https://github.com/casey/just) (`justfile`) — use `just install`, `just test`, `just lint`, `just format`, and `just check` for local development
- Single settings source class: `VaultConfigSettingsSource`
- Vault API coordination: `InternalHttpVault`
- Async supported via event loop management, sync fallback via thread executor
- All critical HTTP logic and field mapping reside in core `__init__.py`
- All fields are always type checked and validated using Pydantic's mechanisms
- **Auth architecture:** one `VaultAuthBackend` implementation per built-in Vault auth method under `features/authentication/`; `InternalHttpVault` delegates login to the selected backend and reuses the returned client token for secret fetches. All phased backends (token, kubernetes, aws, gcp, azure, jwt, oidc, cert, ldap, oci, userpass, github, okta, kerberos, radius, alicloud, cf, pcf) are implemented; AppRole remains the default for backward compatibility.
