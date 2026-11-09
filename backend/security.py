"""Sécurité : hachage des mots de passe (scrypt, stdlib) et jetons JWT (HS256)."""
import base64
import hashlib
import hmac
import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

logger = logging.getLogger("career_finder.security")

JWT_ALGORITHM = "HS256"
TOKEN_TTL_HOURS = int(os.getenv("TOKEN_TTL_HOURS", "12"))

# scrypt : N=2**14, r=8, p=1 (valeurs recommandées par OWASP pour un usage interactif)
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def _load_secret() -> str:
    secret = os.getenv("SECRET_KEY", "")
    if secret and len(secret) >= 32:
        return secret
    generated = secrets.token_urlsafe(48)
    logger.warning(
        "SECRET_KEY absente ou trop courte (<32 car.) : une clé temporaire est générée. "
        "Les sessions seront invalidées à chaque redémarrage. Définis SECRET_KEY dans .env."
    )
    return generated


SECRET_KEY = _load_secret()


# ---------- Mots de passe ----------

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
        return hmac.compare_digest(dk, expected)
    except (ValueError, TypeError):
        return False


# ---------- JWT ----------

def create_access_token(username: str, is_admin: bool = False) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "adm": bool(is_admin),
        "iat": now,
        "exp": now + timedelta(hours=TOKEN_TTL_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """Retourne le payload si le jeton est valide et non expiré, sinon None."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


# ---------- Limiteur de tentatives de connexion (en mémoire) ----------

class LoginRateLimiter:
    """Bloque un identifiant après `max_attempts` échecs dans `window` secondes."""

    def __init__(self, max_attempts: int = 5, window: int = 300):
        self.max_attempts = max_attempts
        self.window = window
        self._failures: dict = {}

    def _recent(self, key: str) -> list:
        now = time.time()
        recent = [t for t in self._failures.get(key, []) if now - t < self.window]
        self._failures[key] = recent
        return recent

    def is_blocked(self, key: str) -> bool:
        return len(self._recent(key)) >= self.max_attempts

    def register_failure(self, key: str) -> None:
        self._recent(key).append(time.time())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
