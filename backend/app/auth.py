from datetime import datetime, timedelta, timezone
import time

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import User
from app.db.session import get_db

_bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(raw_password: str) -> str:
    return bcrypt.hashpw(raw_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(raw_password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(raw_password.encode("utf-8"), password_hash.encode("utf-8"))


# Checked when no account matches, so an unknown email costs the same ~250ms as a wrong password
# instead of returning instantly and revealing which addresses are registered.
_ABSENT_ACCOUNT_HASH = bcrypt.hashpw(b"no-such-account", bcrypt.gensalt()).decode("utf-8")


def verify_password_constant_time(raw_password: str, password_hash: str | None) -> bool:
    if password_hash is None:
        verify_password(raw_password, _ABSENT_ACCOUNT_HASH)
        return False
    return verify_password(raw_password, password_hash)


# Failed logins per (email, client IP). Passwords are the one secret an outsider can guess at will,
# so repeated misses are throttled; the state is per-process, which suits a single-instance deployment.
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300.0
_MAX_TRACKED_KEYS = 10_000
_login_failures: dict[tuple[str, str], list[float]] = {}


def _recent(timestamps: list[float], now: float) -> list[float]:
    return [stamp for stamp in timestamps if now - stamp < LOGIN_WINDOW_SECONDS]


def _sweep_expired(now: float) -> None:
    """Keep an attacker who rotates the email address from growing the table without bound."""
    for key in [key for key, stamps in _login_failures.items() if not _recent(stamps, now)]:
        del _login_failures[key]


def login_retry_after(email: str, client_ip: str) -> float:
    """Seconds the caller must wait before another attempt, or 0.0 when one is allowed."""
    now = time.monotonic()
    attempts = _recent(_login_failures.get((email.lower(), client_ip), []), now)
    if len(attempts) < LOGIN_MAX_ATTEMPTS:
        return 0.0
    return LOGIN_WINDOW_SECONDS - (now - attempts[0])


def record_login_failure(email: str, client_ip: str) -> None:
    now = time.monotonic()
    if len(_login_failures) >= _MAX_TRACKED_KEYS:
        _sweep_expired(now)
    key = (email.lower(), client_ip)
    _login_failures[key] = _recent(_login_failures.get(key, []), now) + [now]


def clear_login_failures(email: str, client_ip: str) -> None:
    _login_failures.pop((email.lower(), client_ip), None)


def create_access_token(user_id: int) -> str:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(user_id), "exp": expires_at}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> int:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        return int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError) as exc:
        raise HTTPException(401, "Invalid or expired token") from exc


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(401, "Not authenticated")
    user_id = decode_access_token(credentials.credentials)
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(401, "User not found")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Admin privileges required")
    return user
