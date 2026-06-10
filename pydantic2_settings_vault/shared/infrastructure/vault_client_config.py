from dataclasses import dataclass


@dataclass(frozen=True)
class VaultClientConfig:
    """Controls for Vault HTTP requests and secret-fetch behavior.

    Pass an instance to ``VaultConfigSettingsSource`` to tune timeouts, retries,
    and concurrency without modifying package internals.
    """

    request_timeout: float = 30.0
    max_concurrent_requests: int = 5
    retry_max_attempts: int = 5
    retry_min_delay: float = 0.1
    retry_max_delay: float = 0.2

    def __post_init__(self) -> None:
        if self.request_timeout <= 0:
            raise ValueError("request_timeout must be greater than 0")
        if self.max_concurrent_requests < 1:
            raise ValueError("max_concurrent_requests must be at least 1")
        if self.retry_max_attempts < 0:
            raise ValueError("retry_max_attempts must be 0 or greater")
        if self.retry_min_delay < 0:
            raise ValueError("retry_min_delay must be 0 or greater")
        if self.retry_max_delay < 0:
            raise ValueError("retry_max_delay must be 0 or greater")
        if self.retry_min_delay > self.retry_max_delay:
            raise ValueError(
                "retry_min_delay must be less than or equal to retry_max_delay"
            )

    @classmethod
    def for_local(cls) -> "VaultClientConfig":
        """Preset tuned for local development (slower Vault, fewer parallel calls)."""
        return cls(
            request_timeout=60.0,
            max_concurrent_requests=3,
            retry_max_attempts=3,
            retry_min_delay=0.2,
            retry_max_delay=1.0,
        )

    @classmethod
    def for_ci(cls) -> "VaultClientConfig":
        """Preset tuned for CI pipelines (fail fast, short timeouts)."""
        return cls(
            request_timeout=15.0,
            max_concurrent_requests=5,
            retry_max_attempts=2,
            retry_min_delay=0.05,
            retry_max_delay=0.2,
        )

    @classmethod
    def for_production(cls) -> "VaultClientConfig":
        """Preset tuned for production (higher concurrency, longer retry backoff)."""
        return cls(
            request_timeout=30.0,
            max_concurrent_requests=10,
            retry_max_attempts=5,
            retry_min_delay=0.1,
            retry_max_delay=2.0,
        )
