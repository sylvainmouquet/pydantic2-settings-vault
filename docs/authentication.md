# Authentication

Select the auth backend with `VAULT_AUTH_METHOD` (default: `approle`). Override the mount path with optional `VAULT_AUTH_MOUNT`.

## Supported methods

| Method | `VAULT_AUTH_METHOD` | Required environment variables |
| --- | --- | --- |
| AppRole (default) | `approle` | `VAULT_ROLE_ID`, `VAULT_SECRET_ID` |
| Token | `token` | `VAULT_TOKEN` |
| Kubernetes | `kubernetes` | `VAULT_K8S_ROLE`, plus `VAULT_K8S_JWT` or service-account token file |
| AWS | `aws` | `VAULT_AWS_ROLE`, plus signed STS request env vars or `botocore` credentials |
| GCP | `gcp` | `VAULT_GCP_ROLE`, plus `VAULT_GCP_JWT` or `GOOGLE_APPLICATION_CREDENTIALS` |
| Azure | `azure` | `VAULT_AZURE_ROLE`, plus `VAULT_AZURE_JWT` or Azure managed identity |
| JWT | `jwt` | `VAULT_JWT_ROLE`, `VAULT_JWT` |
| OIDC | `oidc` | `VAULT_OIDC_ROLE`, plus `VAULT_OIDC_JWT` or `VAULT_OIDC_ID_TOKEN` |
| Cert | `cert` | `VAULT_CLIENT_CERT`, `VAULT_CLIENT_KEY`, optional `VAULT_CERT_NAME` |
| LDAP | `ldap` | `VAULT_LDAP_USERNAME`, `VAULT_LDAP_PASSWORD` |
| OCI | `oci` | `VAULT_OCI_ROLE`, plus signed request headers or `oci` SDK credentials |
| Userpass | `userpass` | `VAULT_USERPASS_USERNAME`, `VAULT_USERPASS_PASSWORD` |
| GitHub | `github` | `VAULT_GITHUB_TOKEN` |
| Okta | `okta` | `VAULT_OKTA_USERNAME`, `VAULT_OKTA_PASSWORD`, optional `VAULT_OKTA_TOTP` |
| Kerberos | `kerberos` | `VAULT_KERBEROS_TOKEN` (base64 SPNEGO token) |
| RADIUS | `radius` | `VAULT_RADIUS_USERNAME`, `VAULT_RADIUS_PASSWORD` |
| Alicloud | `alicloud` | `VAULT_ALICLOUD_ROLE`, plus pre-signed STS request env vars |
| CF | `cf` | `VAULT_CF_ROLE`, plus instance cert/key or pre-signed login fields |
| PCF | `pcf` | Same as CF (`VAULT_CF_ROLE`, instance cert/key or pre-signed fields) |

## Common variables

These apply to every auth method:

| Variable | Default | Description |
| --- | --- | --- |
| `VAULT_URL` | `http://127.0.0.1:8200` | Vault API address |
| `VAULT_NAMESPACE` | — | Optional Enterprise namespace |
| `VAULT_KV_VERSION` | `2` | KV engine version (`1` or `2`) |
| `VAULT_AUTH_MOUNT` | method name | Auth mount override (defaults match each method name above) |

## Method notes

### AppRole (default)

Set `VAULT_ROLE_ID` and `VAULT_SECRET_ID`. See the [usage guide](usage.md#recommended-vault-policies) for policy and role setup.

### Token

Uses a pre-issued token directly; no login call is made.

```python
import os

os.environ["VAULT_AUTH_METHOD"] = "token"
os.environ["VAULT_TOKEN"] = "<token>"
os.environ["VAULT_URL"] = "https://vault.example.com:8200"
```

### Kubernetes

Reads the service-account JWT from `VAULT_K8S_JWT` or, by default, `/var/run/secrets/kubernetes.io/serviceaccount/token`.

```python
import os

os.environ["VAULT_AUTH_METHOD"] = "kubernetes"
os.environ["VAULT_K8S_ROLE"] = "<vault role>"
os.environ["VAULT_URL"] = "https://vault.example.com:8200"
# Optional: os.environ["VAULT_K8S_JWT"] = "<service account jwt>"
# Optional: os.environ["VAULT_AUTH_MOUNT"] = "kubernetes"
```

### AWS

Signs an STS `GetCallerIdentity` request with instance profile, environment keys, or web identity when `botocore` is installed (`pip install pydantic2-settings-vault[aws]`). You can also supply a pre-signed request via `VAULT_AWS_IAM_REQUEST_URL`, `VAULT_AWS_IAM_REQUEST_BODY`, and `VAULT_AWS_IAM_REQUEST_HEADERS`.

### GCP

Obtains a service-account JWT from `google-auth` when installed (`pip install pydantic2-settings-vault[gcp]`), or from `VAULT_GCP_JWT`.

### Azure

Obtains a managed-identity or service-principal token from `azure-identity` when installed (`pip install pydantic2-settings-vault[azure]`), or from `VAULT_AZURE_JWT`.

### JWT

Sends a signed bearer token to the JWT auth mount (`POST /v1/auth/jwt/login`).

### OIDC

Sends an OIDC ID token to the OIDC/JWT mount. Use `VAULT_OIDC_JWT` or `VAULT_OIDC_ID_TOKEN`. For Microsoft Entra ID distributed claims, set optional `VAULT_OIDC_DISTRIBUTED_CLAIM_ACCESS_TOKEN`.

### Cert

Presents a TLS client certificate during login (`POST /v1/auth/cert/login`). Set `VAULT_CLIENT_CERT` and `VAULT_CLIENT_KEY`; optionally `VAULT_CERT_NAME` to target a specific certificate role.

### LDAP

Binds with username and password (`POST /v1/auth/ldap/login/<username>`).

### OCI

Signs a GET request to the OCI login endpoint. Provide pre-signed headers via `VAULT_OCI_REQUEST_HEADERS`, or install `oci` (`pip install pydantic2-settings-vault[oci]`) and use instance principal (`VAULT_OCI_AUTH_TYPE=instance`, default) or API key (`VAULT_OCI_AUTH_TYPE=api_key` with standard OCI config).

### Userpass

Binds with username and password (`POST /v1/auth/userpass/login/<username>`).

### GitHub

Sends a personal access token (`POST /v1/auth/github/login`).

### Okta

Binds with username and password against Okta (`POST /v1/auth/okta/login/<username>`). Set optional `VAULT_OKTA_TOTP` and `VAULT_OKTA_MFA_PROVIDER` when MFA is required.

### Kerberos

Sends a pre-generated SPNEGO token in the `Authorization: Negotiate` header (`POST /v1/auth/kerberos/login`). Set `VAULT_KERBEROS_TOKEN` to the base64 token value (without the `Negotiate` prefix).

### RADIUS

Binds with username and password (`POST /v1/auth/radius/login/<username>`).

### Alicloud

Verifies a signed STS `GetCallerIdentity` request. Provide `VAULT_ALICLOUD_IDENTITY_REQUEST_URL` and `VAULT_ALICLOUD_IDENTITY_REQUEST_HEADERS` (base64-encoded values from `vault login -method=alicloud` or your own signer).

### CF and PCF

Signs the instance identity certificate with `CF_INSTANCE_KEY` (`POST /v1/auth/cf/login`). On a CF instance, set `VAULT_CF_ROLE` and rely on `CF_INSTANCE_CERT` / `CF_INSTANCE_KEY`, or provide `VAULT_CF_SIGNING_TIME` and `VAULT_CF_SIGNATURE`. Install `cryptography` (`pip install pydantic2-settings-vault[cf]`) to generate signatures locally.

PCF auth uses the same login payload as CF against the legacy `pcf` mount (`POST /v1/auth/pcf/login`).

## Related documentation

- [Usage guide](usage.md) — end-to-end setup and field annotations
- [Vault KV & policies](vault-kv-and-policies.md) — KV paths and policy examples
