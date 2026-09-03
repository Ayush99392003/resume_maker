"""Local username/password profiles with per-provider encrypted API keys."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_username(username: str) -> str:
    return "".join(
        c for c in username.lower().strip() if c.isalnum() or c in "._-"
    )


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        120_000,
    ).hex()


def _atomic_write_text(path: Path, content: str) -> None:
    """Write text atomically via temporary file and os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
        suffix=".tmp",
    ) as tf:
        tf.write(content)
        temp_path = Path(tf.name)
    try:
        os.replace(temp_path, path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


# ---------------------------------------------------------------------------
# Encryption helpers (Fernet / AES-128-CBC + HMAC-SHA256)
# ---------------------------------------------------------------------------


def _derive_fernet_key(secret: str) -> bytes:
    """Derive a 32-byte Fernet-compatible key from SESSION_SECRET via PBKDF2."""
    raw = hashlib.pbkdf2_hmac(
        "sha256",
        secret.encode("utf-8"),
        b"resume_maker_provider_cfg_v1",
        200_000,
        dklen=32,
    )
    return base64.urlsafe_b64encode(raw)


def _get_fernet():
    """Return a Fernet cipher keyed from SESSION_SECRET env var."""
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise ImportError(
            "Install cryptography: pip install cryptography"
        ) from exc
    secret = os.getenv("SESSION_SECRET", "").strip()
    if not secret:
        # Fall back to a deterministic but weak key so the app still runs
        # without a .env file; warn loudly.
        import warnings
        warnings.warn(
            "SESSION_SECRET is not set — provider credentials are NOT "
            "encrypted. Set SESSION_SECRET in .env for production.",
            stacklevel=3,
        )
        secret = "INSECURE_DEFAULT_DO_NOT_USE_IN_PRODUCTION"
    return Fernet(_derive_fernet_key(secret))


def _encrypt_config(cfg: "ProviderConfig") -> str:
    """Return an encrypted, base64-safe token for a ProviderConfig."""
    f = _get_fernet()
    payload = cfg.model_dump_json().encode("utf-8")
    return f.encrypt(payload).decode("ascii")


def _decrypt_config(token: str) -> Optional[Dict[str, Any]]:
    """Decrypt a stored provider config token; returns None on any failure."""
    if not token:
        return None
    try:
        f = _get_fernet()
        payload = f.decrypt(token.encode("ascii"))
        return json.loads(payload)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Per-provider credential schema
# ---------------------------------------------------------------------------


class ProviderConfig(BaseModel):
    """All credential fields across every supported provider.

    Only the fields relevant to the selected provider need to be set.
    """

    # ── Simple key providers: OpenAI, Groq, Gemini, Anthropic ──────────────
    api_key: str = ""
    model: str = ""

    # ── Azure OpenAI ────────────────────────────────────────────────────────
    endpoint: str = ""         # https://<resource>.openai.azure.com/
    deployment: str = ""       # Azure deployment / resource name
    api_version: str = "2024-02-01"

    # ── AWS Bedrock ─────────────────────────────────────────────────────────
    access_key_id: str = ""
    secret_access_key: str = ""
    region: str = "us-east-1"
    model_id: str = ""         # e.g. amazon.nova-pro-v1:0

    def is_configured(self, provider: str) -> bool:
        """Return True when the minimum required fields are populated."""
        p = provider.strip().lower()
        if p == "azure":
            return bool(self.api_key and self.endpoint and self.deployment)
        if p == "aws":
            return bool(self.access_key_id and self.secret_access_key)
        return bool(self.api_key)

    def masked_hint(self) -> str:
        """Return a short masked hint for display (never the raw value)."""
        key = self.api_key or self.access_key_id or ""
        if not key:
            return ""
        key = key.strip()
        if len(key) <= 8:
            return "***"
        return f"{key[:4]}...{key[-4:]}"

    def fields_set_names(self, provider: str) -> List[str]:
        """Return names of fields that are non-empty for this provider."""
        p = provider.strip().lower()
        candidates: Dict[str, str] = {}
        if p in ("openai", "groq", "gemini", "anthropic"):
            candidates = {"api_key": self.api_key, "model": self.model}
        elif p == "azure":
            candidates = {
                "api_key": self.api_key,
                "endpoint": self.endpoint,
                "deployment": self.deployment,
                "api_version": self.api_version,
                "model": self.model,
            }
        elif p == "aws":
            candidates = {
                "access_key_id": self.access_key_id,
                "secret_access_key": self.secret_access_key,
                "region": self.region,
                "model_id": self.model_id,
            }
        return [k for k, v in candidates.items() if (v or "").strip()]


# ---------------------------------------------------------------------------
# User profile
# ---------------------------------------------------------------------------


class UserProfile(BaseModel):
    username: str
    password_hash: str
    salt: str
    default_provider: str = "groq"
    default_model: str = "openai/gpt-oss-120b"
    # provider name → encrypted ProviderConfig blob
    provider_configs: Dict[str, str] = Field(default_factory=dict)
    # Legacy field kept for migration only — no longer written for new data
    api_keys: Dict[str, str] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_utcnow)
    updated_at: str = Field(default_factory=_utcnow)

    def public_dict(self) -> Dict[str, Any]:
        """Never expose raw secrets or password hash to the client."""
        configured: Dict[str, bool] = {}
        hints: Dict[str, str] = {}
        for p in ("groq", "openai", "gemini", "anthropic", "azure", "aws"):
            cfg = _decrypt_config(self.provider_configs.get(p, ""))
            if cfg:
                pc = ProviderConfig(**cfg)
                configured[p] = pc.is_configured(p)
                hints[p] = pc.masked_hint() if configured[p] else ""
            else:
                configured[p] = False
                hints[p] = ""
        return {
            "username": self.username,
            "default_provider": self.default_provider,
            "default_model": self.default_model,
            "keys_configured": configured,
            "key_hints": hints,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ---------------------------------------------------------------------------
# Auth store
# ---------------------------------------------------------------------------


class AuthStore:
    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is None:
            base_dir = (
                Path(__file__).resolve().parent.parent / "data" / "profiles"
            )
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.tokens_path = self.base_dir.parent / "tokens.json"
        self._tokens: Dict[str, str] = self._load_tokens()

    def _profile_path(self, username: str) -> Path:
        return self.base_dir / f"{_norm_username(username)}.json"

    def _load_tokens(self) -> Dict[str, str]:
        if not self.tokens_path.exists():
            return {}
        try:
            return json.loads(self.tokens_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_tokens(self) -> None:
        _atomic_write_text(
            self.tokens_path, json.dumps(self._tokens, indent=2)
        )

    # ------------------------------------------------------------------
    # Migration: old api_keys dict → encrypted provider_configs
    # ------------------------------------------------------------------

    def _migrate_legacy_keys(self, user: UserProfile) -> UserProfile:
        """Auto-convert plain api_keys → encrypted provider_configs on load."""
        if not user.api_keys:
            return user
        changed = False
        for provider, raw_key in user.api_keys.items():
            p = provider.strip().lower()
            if not raw_key or p in user.provider_configs:
                continue
            cfg = ProviderConfig(api_key=raw_key)
            user.provider_configs[p] = _encrypt_config(cfg)
            changed = True
        if changed:
            user.api_keys = {}  # wipe legacy plain-text field
            self.save_user(user)
        return user

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def get_user(self, username: str) -> Optional[UserProfile]:
        path = self._profile_path(username)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        # Back-compat: old profiles have no provider_configs key
        data.setdefault("provider_configs", {})
        data.setdefault("api_keys", {})
        user = UserProfile(**data)
        # Normalise stale model names
        if user.default_model in (
            "llama-3.3-70b-versatile",
            "llama-3.1-70b-versatile",
            "gpt-oss-120b",
        ):
            user.default_model = "openai/gpt-oss-120b"
            self.save_user(user)
        user = self._migrate_legacy_keys(user)
        return user

    def save_user(self, user: UserProfile) -> UserProfile:
        user.updated_at = _utcnow()
        path = self._profile_path(user.username)
        _atomic_write_text(path, user.model_dump_json(indent=2))
        return user

    def register(self, username: str, password: str) -> UserProfile:
        uname = _norm_username(username)
        if len(uname) < 2:
            raise ValueError("Username must be at least 2 characters")
        if len(password) < 4:
            raise ValueError("Password must be at least 4 characters")
        if self.get_user(uname):
            raise ValueError("Username already exists")
        salt = secrets.token_hex(16)
        user = UserProfile(
            username=uname,
            salt=salt,
            password_hash=_hash_password(password, salt),
        )
        return self.save_user(user)

    def authenticate(self, username: str, password: str) -> UserProfile:
        user = self.get_user(username)
        if not user:
            raise ValueError("Invalid username or password")
        if user.password_hash != _hash_password(password, user.salt):
            raise ValueError("Invalid username or password")
        return user

    def change_password(
        self, user: UserProfile, current_password: str, new_password: str
    ) -> UserProfile:
        if user.password_hash != _hash_password(current_password, user.salt):
            raise ValueError("Current password is incorrect")
        if len(new_password) < 4:
            raise ValueError("New password must be at least 4 characters")
        user.salt = secrets.token_hex(16)
        user.password_hash = _hash_password(new_password, user.salt)
        return self.save_user(user)

    def create_token(self, username: str) -> str:
        token = secrets.token_urlsafe(32)
        self._tokens = self._load_tokens()
        self._tokens[token] = _norm_username(username)
        self._save_tokens()
        return token

    def revoke_token(self, token: str) -> None:
        self._tokens = self._load_tokens()
        if token in self._tokens:
            del self._tokens[token]
            self._save_tokens()

    def user_from_token(self, token: Optional[str]) -> Optional[UserProfile]:
        if not token:
            return None
        self._tokens = self._load_tokens()
        username = self._tokens.get(token.strip())
        if not username:
            return None
        return self.get_user(username)

    # ------------------------------------------------------------------
    # Per-provider credential management
    # ------------------------------------------------------------------

    def set_provider_config(
        self,
        user: UserProfile,
        provider: str,
        cfg: ProviderConfig,
    ) -> UserProfile:
        """Encrypt and store a ProviderConfig for one provider."""
        p = provider.strip().lower()
        user.provider_configs[p] = _encrypt_config(cfg)
        return self.save_user(user)

    def get_provider_config(
        self,
        user: Optional[UserProfile],
        provider: str,
    ) -> Optional[ProviderConfig]:
        """Decrypt and return a ProviderConfig, or None if not configured."""
        if not user:
            return None
        p = provider.strip().lower()
        token = user.provider_configs.get(p, "")
        data = _decrypt_config(token)
        if not data:
            return None
        try:
            return ProviderConfig(**data)
        except Exception:
            return None

    def delete_provider_config(
        self, user: UserProfile, provider: str
    ) -> UserProfile:
        """Remove a provider's credentials."""
        p = provider.strip().lower()
        user.provider_configs.pop(p, None)
        return self.save_user(user)

    # ------------------------------------------------------------------
    # Backward-compat helpers (still used by existing api_key resolution)
    # ------------------------------------------------------------------

    def set_api_keys(
        self,
        user: UserProfile,
        keys: Dict[str, str],
        *,
        clear: Optional[List[str]] = None,
    ) -> UserProfile:
        """Update simple api_key field via the new encrypted store.

        Pass provider names in `clear` to remove credentials.
        """
        for provider in clear or []:
            user = self.delete_provider_config(user, provider)

        for provider, key in (keys or {}).items():
            k = (key or "").strip()
            if not k:
                continue
            existing = self.get_provider_config(user, provider) or ProviderConfig()
            existing.api_key = k
            user = self.set_provider_config(user, provider, existing)
        return user

    def get_api_key(
        self, user: Optional[UserProfile], provider: str
    ) -> Optional[str]:
        cfg = self.get_provider_config(user, provider)
        if not cfg:
            return None
        key = (cfg.api_key or "").strip()
        return key or None

    def list_usernames(self) -> List[str]:
        return sorted(p.stem for p in self.base_dir.glob("*.json"))


auth_store = AuthStore()
