"""Authenticated encryption helpers for operator-managed provider keys."""

from __future__ import annotations

import base64
import hashlib
import json

from core.config import settings


def _fernet():
    """Build a Fernet cipher from an injected master secret."""
    from cryptography.fernet import Fernet

    master = settings.ai_settings_encryption_key or settings.jwt_secret
    digest = hashlib.sha256(master.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_api_keys(keys: dict[str, str]) -> str:
    """Encrypt a provider-to-key mapping for database storage."""
    clean = {name: value for name, value in keys.items() if value}
    return _fernet().encrypt(json.dumps(clean, sort_keys=True).encode("utf-8")).decode("ascii")


def decrypt_api_keys(ciphertext: str | None) -> dict[str, str]:
    """Decrypt stored provider keys; corrupt ciphertext fails closed."""
    if not ciphertext:
        return {}
    try:
        decoded = _fernet().decrypt(ciphertext.encode("ascii"))
        values = json.loads(decoded.decode("utf-8"))
        return {str(key): str(value) for key, value in values.items() if value}
    except Exception:  # noqa: BLE001 - never prevent startup over stale secret data
        return {}
