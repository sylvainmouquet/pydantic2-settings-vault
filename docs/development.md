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
