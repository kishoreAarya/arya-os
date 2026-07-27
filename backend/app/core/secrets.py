"""
Secrets layer.

Beginner note: this is a thin, deliberate wrapper — not a Vault client.
The point isn't cleverness, it's a single chokepoint. Today every
secret comes from `Settings` (which itself reads `.env` via
pydantic-settings). If you outgrow that later — HashiCorp Vault, AWS
Secrets Manager, GCP Secret Manager — you swap the body of `get()`
and nothing else in the codebase changes, because nothing else in the
codebase is allowed to call `os.environ` for a secret directly.

Rule enforced by convention (and worth a grep in CI later):
    grep -rn "os.environ" backend/app --include="*.py" | grep -v secrets.py
should only ever return this file.
"""
from app.core.config import Settings, get_settings


class SecretNotConfigured(RuntimeError):
    """Raised when code asks for a secret that isn't set anywhere."""


class SecretsManager:
    """Every provider/agent asks THIS for a key — never `Settings`
    directly, never `os.environ` directly. Keeps provider code
    identical regardless of where secrets actually live."""

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()

    def get(self, name: str, required: bool = True) -> str | None:
        """`name` is the Settings field name, e.g. 'runpod_api_key'."""
        value = getattr(self._settings, name, None)
        if required and not value:
            raise SecretNotConfigured(
                f"Secret '{name}' is not configured. Set it in .env."
            )
        return value

    # --- Future backends plug in here without touching call sites ---
    # def _get_from_vault(self, name: str) -> str | None: ...
    # def _get_from_aws_secrets_manager(self, name: str) -> str | None: ...


_secrets_manager: SecretsManager | None = None


def get_secrets_manager() -> SecretsManager:
    global _secrets_manager
    if _secrets_manager is None:
        _secrets_manager = SecretsManager()
    return _secrets_manager
