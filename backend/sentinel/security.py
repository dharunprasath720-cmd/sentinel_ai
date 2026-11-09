"""Password hashing (argon2), JWT tokens and role checks."""
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

ALGORITHM = "HS256"
_hasher = PasswordHasher()


class AuthError(Exception):
    """Missing, malformed, expired or tampered credentials (HTTP 401)."""


class Forbidden(Exception):
    """Authenticated but not allowed (HTTP 403)."""


class NotFound(Exception):
    """Unknown id, or an id that belongs to another business (HTTP 404, never 403)."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def create_token(user, secret: str, ttl_minutes: int = 60) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user.id), "username": user.username, "role": user.role,
                       "business_id": user.business_id, "iat": now,
                       "exp": now + timedelta(minutes=ttl_minutes)}, secret, algorithm=ALGORITHM)


def decode_token(token: str, secret: str) -> dict:
    try:
        return jwt.decode(token, secret, algorithms=[ALGORITHM],
                          options={"require": ["exp", "sub"]})
    except jwt.PyJWTError as exc:
        raise AuthError(str(exc)) from exc


def require_role(role: str, allowed: set[str]) -> None:
    if role not in allowed:
        raise Forbidden(f"role '{role}' may not perform this action")
