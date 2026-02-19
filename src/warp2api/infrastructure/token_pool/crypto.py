from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from warp2api.observability.logging import logger


def _derive_key_material() -> bytes:
    raw = (os.getenv("WARP_TOKEN_ENCRYPTION_KEY") or "").strip()
    if raw:
        try:
            decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
            if len(decoded) == 32:
                return decoded
        except Exception:
            pass
        logger.warning("WARP_TOKEN_ENCRYPTION_KEY is invalid, fallback key derivation will be used")

    seed = (
        (os.getenv("ADMIN_TOKEN") or "")
        + "|"
        + (os.getenv("API_TOKEN") or "")
        + "|"
        + (os.getenv("WARP_REFRESH_TOKEN_B64") or "")
    )
    logger.warning("Using derived encryption key fallback; set WARP_TOKEN_ENCRYPTION_KEY for production")
    return hashlib.sha256(seed.encode("utf-8")).digest()


_KEY = _derive_key_material()


def encrypt_refresh_token(plaintext: str) -> str:
    token = (plaintext or "").strip()
    if not token:
        raise ValueError("refresh token is empty")
    nonce = os.urandom(12)
    aesgcm = AESGCM(_KEY)
    ciphertext = aesgcm.encrypt(nonce, token.encode("utf-8"), associated_data=None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt_refresh_token(ciphertext_b64: str) -> str:
    raw = base64.urlsafe_b64decode(ciphertext_b64.encode("ascii"))
    if len(raw) < 13:
        raise ValueError("invalid encrypted token payload")
    nonce, ciphertext = raw[:12], raw[12:]
    aesgcm = AESGCM(_KEY)
    plain = aesgcm.decrypt(nonce, ciphertext, associated_data=None)
    return plain.decode("utf-8")


def token_hash(token: str) -> str:
    return hashlib.sha256((token or "").strip().encode("utf-8")).hexdigest()


def token_preview(token: str) -> str:
    t = (token or "").strip()
    if not t:
        return ""
    if len(t) <= 10:
        return t[:2] + "***"
    return f"{t[:6]}...{t[-4:]}"

