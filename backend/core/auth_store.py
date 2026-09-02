"""Local username/password profiles with per-provider API keys."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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


class UserProfile(BaseModel):
    username: str
    password_hash: str
    salt: str
    default_provider: str = "groq"
    default_model: str = "openai/gpt-oss-120b"
    api_keys: Dict[str, str] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_utcnow)
    updated_at: str = Field(default_factory=_utcnow)

    def public_dict(self) -> Dict[str, Any]:
        """Never expose raw API keys or password hash to the client."""
        keys_status = {
            p: False
            for p in ("groq", "openai", "gemini", "anthropic", "azure", "aws")
        }
        for p, k in self.api_keys.items():
            keys_status[p] = bool((k or "").strip())
        return {
            "username": self.username,
            "default_provider": self.default_provider,
            "default_model": self.default_model,
            "keys_configured": keys_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


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
        self.tokens_path.parent.mkdir(parents=True, exist_ok=True)
        self.tokens_path.write_text(
            json.dumps(self._tokens, indent=2), encoding="utf-8"
        )

    def get_user(self, username: str) -> Optional[UserProfile]:
        path = self._profile_path(username)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        user = UserProfile(**data)
        if user.default_model in (
            "llama-3.3-70b-versatile",
            "llama-3.1-70b-versatile",
            "gpt-oss-120b",
        ):
            user.default_model = "openai/gpt-oss-120b"
            self.save_user(user)
        return user

    def save_user(self, user: UserProfile) -> UserProfile:
        user.updated_at = _utcnow()
        path = self._profile_path(user.username)
        path.write_text(user.model_dump_json(indent=2), encoding="utf-8")
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
        self._tokens[token] = _norm_username(username)
        self._save_tokens()
        return token

    def revoke_token(self, token: str) -> None:
        if token in self._tokens:
            del self._tokens[token]
            self._save_tokens()

    def user_from_token(self, token: Optional[str]) -> Optional[UserProfile]:
        if not token:
            return None
        username = self._tokens.get(token.strip())
        if not username:
            return None
        return self.get_user(username)

    def set_api_keys(
        self,
        user: UserProfile,
        keys: Dict[str, str],
        *,
        clear: Optional[List[str]] = None,
    ) -> UserProfile:
        """Update keys. Empty values are ignored (do not wipe).

        Pass provider names in `clear` to remove a key intentionally.
        """
        for provider in clear or []:
            p = provider.strip().lower()
            if p in user.api_keys:
                del user.api_keys[p]

        for provider, key in (keys or {}).items():
            p = provider.strip().lower()
            k = (key or "").strip()
            if not k:
                continue  # never wipe on empty — browser password fields do this
            user.api_keys[p] = k
        return self.save_user(user)

    def get_api_key(
        self, user: Optional[UserProfile], provider: str
    ) -> Optional[str]:
        if not user:
            return None
        key = (user.api_keys.get(provider.strip().lower()) or "").strip()
        return key or None

    def list_usernames(self) -> List[str]:
        return sorted(p.stem for p in self.base_dir.glob("*.json"))


auth_store = AuthStore()
