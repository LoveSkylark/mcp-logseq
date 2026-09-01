"""Environment settings for the DB-only server."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    api_url: str
    api_token: str
    connect_timeout: float
    read_timeout: float
    verify_ssl: bool

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("LOGSEQ_API_TOKEN", "").strip()
        if not token:
            raise RuntimeError("LOGSEQ_API_TOKEN is required")
        return cls(
            api_url=os.getenv("LOGSEQ_API_URL", "http://127.0.0.1:12315").strip(),
            api_token=token,
            connect_timeout=_positive_float("LOGSEQ_API_CONNECT_TIMEOUT", 3.0),
            read_timeout=_positive_float("LOGSEQ_API_READ_TIMEOUT", 15.0),
            verify_ssl=os.getenv("LOGSEQ_VERIFY_SSL", "true").lower()
            not in {"0", "false", "no"},
        )


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be a positive number") from error
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive number")
    return value