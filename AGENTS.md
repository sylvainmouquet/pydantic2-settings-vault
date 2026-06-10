# AGENTS.md

## Agent Role: pydantic2-settings-vault

### Primary Responsibility
This module acts as a bridge between HashiCorp Vault and Pydantic v2's settings system, securely injecting secrets into application configuration at runtime.

### Agent Responsibilities & Capabilities
- Authenticate with Vault using AppRole (via env variables).
- Retrieve configuration secrets for Pydantic fields from Vault paths/keys.
- Limit concurrency and handle async secret fetching robustly.
- Log errors and integration events with sufficient granularity.
- Support for future extension to new backends or authentication schemes.

---

## Agent – Keywords & Concepts
- `InternalHttpVault`: Handles all Vault HTTP communication and authentication.
- `VaultConfigSettingsSource`: Implements the secret sourcing logic for Pydantic settings.
- "Field mapping": Each Pydantic field may be mapped to a `vault_secret_path` and `vault_secret_key`. 

---

## Usage Scenario
When a Pydantic settings model includes fields tagged with Vault metadata, the source class:
- Authenticates to Vault with AppRole
- Discovers the relevant Vault paths & keys per field
- Loads secret values and provides them to the model during initialization

---

## Future Agents/Extensions
Consider implementing additional agents/extensions for:
- Other secret backends (AWS Secrets Manager, Azure Key Vault, GCP Secret Manager)
- Dynamic secret renewal agents (long-lived processes for renewing Vault tokens)
- Audit/reconciliation agents (verifying secrets and usage over time)

---

## Development

Use the project `justfile` for all local tasks:

```bash
just install
just test
just coverage
just lint
just format
just type-check
just check
just docs-serve
just docs-build
```

---

## Contact
For questions, open issues or submit PRs on the project repository.