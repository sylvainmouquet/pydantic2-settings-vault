import time
from dataclasses import dataclass

from pydantic import SecretStr

_CACHE_KEY = tuple[str, int]


@dataclass(frozen=True)
class _CacheEntry:
    secrets: dict[str, SecretStr]
    expires_at: float


class VaultSecretCache:
    """In-memory cache for Vault path secrets with optional TTL."""

    def __init__(self, *, ttl_seconds: float | None = None) -> None:
        self._ttl_seconds = ttl_seconds
        self._entries: dict[_CACHE_KEY, _CacheEntry] = {}

    def get(self, vault_path: str, kv_version: int) -> dict[str, SecretStr] | None:
        key = (vault_path, kv_version)
        entry = self._entries.get(key)
        if entry is None:
            return None
        if time.monotonic() >= entry.expires_at:
            del self._entries[key]
            return None
        return entry.secrets

    def set(
        self,
        vault_path: str,
        kv_version: int,
        secrets: dict[str, SecretStr],
    ) -> None:
        expires_at = (
            time.monotonic() + self._ttl_seconds
            if self._ttl_seconds is not None
            else float("inf")
        )
        self._entries[(vault_path, kv_version)] = _CacheEntry(
            secrets=secrets,
            expires_at=expires_at,
        )

    def clear(self) -> None:
        self._entries.clear()


_shared_secret_cache: VaultSecretCache | None = None


def get_shared_secret_cache(*, ttl_seconds: float | None = None) -> VaultSecretCache:
    """Return the module-level shared cache, creating it on first use."""
    global _shared_secret_cache
    if _shared_secret_cache is None:
        _shared_secret_cache = VaultSecretCache(ttl_seconds=ttl_seconds)
    return _shared_secret_cache


def reset_shared_secret_cache() -> None:
    """Clear and discard the module-level shared cache (intended for tests)."""
    global _shared_secret_cache
    if _shared_secret_cache is not None:
        _shared_secret_cache.clear()
    _shared_secret_cache = None
