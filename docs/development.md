# Development

## Prerequisites

- [uv](https://docs.astral.sh/uv/)
- [just](https://github.com/casey/just/)

## Setup

```bash
just install
```

## Common tasks

| Command | Description |
| --- | --- |
| `just test` | Run the test suite |
| `just coverage` | Run tests with 100% coverage enforcement |
| `just lint` | Ruff check and format verification |
| `just format` | Auto-fix lint issues and format code |
| `just type-check` | Pyright static analysis |
| `just check` | Lint, type-check, and test |
| `just build` | Build the package (`VERSION` env var required) |
| `just update` | Upgrade locked dependencies |
| `just check-deps` | List outdated dependencies |

List every recipe:

```bash
just --list
```

## Testing

The suite combines **unit tests with mocked Vault HTTP responses** and **integration tests against a real Vault container**.

| Area | Location | Notes |
| --- | --- | --- |
| Vault HTTP client | `test/features/shared/test_vault_http.py` | Auth, secret fetch, HTTP errors, network failures |
| Settings source | `test/features/settings_source/test_source.py` | Field mapping, missing keys, failure propagation |
| Auth backends | `test/features/authentication/test_backends.py` | Payload building and login mocking |
| Shared mocks | `test/features/shared/vault_mocks.py` | Reusable aiohttp and `InternalHttpVault` helpers |
| Integration | `test/features/settings_source/test_settings.py` | Requires Docker/Podman (`vault_container` fixture) |

Run only fast unit tests (no container):

```bash
just test -k "not vault_container"
```

Run the full suite including integration tests:

```bash
just test
```
