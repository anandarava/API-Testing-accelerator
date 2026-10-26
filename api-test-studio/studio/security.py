import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException

PAIRING_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    derived = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32)
    return f'scrypt${salt}${derived.hex()}'


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, _ = stored.split('$')
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, salt), stored)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_pairing_code() -> str:
    return ''.join(secrets.choice(PAIRING_ALPHABET) for _ in range(8))


def normalize_pairing_code(code: str) -> str:
    return ''.join(ch for ch in code.upper() if ch.isalnum())


class RateLimiter:
    """Small in-memory sliding-window limiter for sign-in and pairing endpoints."""

    def __init__(self, limit: int, window: float = 60):
        self.limit, self.window = limit, window
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def check(self, key: str):
        current = time.time()
        with self.lock:
            hits = self.hits[key]
            while hits and hits[0] < current - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                raise HTTPException(429, 'Too many attempts. Wait a minute and try again.')
            hits.append(current)

    def reset(self):
        with self.lock:
            self.hits.clear()


auth_limiter = RateLimiter(20)
pairing_limiter = RateLimiter(20)
