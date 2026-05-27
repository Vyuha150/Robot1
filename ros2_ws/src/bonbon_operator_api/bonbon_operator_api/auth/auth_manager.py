"""AuthManager — JWT issuance and local SQLite user store.

JWT secrets are NEVER hardcoded.  All secrets come from OperatorAPIConfig.

Password hashing uses PBKDF2-HMAC-SHA256 (stdlib) — no extra deps.
For production deployments with passlib installed, bcrypt is used instead.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
import time
import uuid
from pathlib import Path

import jwt

from bonbon_operator_api.auth.role_permissions import VALID_ROLES
from bonbon_operator_api.models.auth_models import TokenPayload, UserCreate, UserInfo, UserUpdate

logger = logging.getLogger(__name__)

_PBKDF2_ITERS = 260_000  # OWASP recommended minimum

# Attempt to use passlib bcrypt for stronger hashing.
# Fall back to PBKDF2 if bcrypt is unavailable or incompatible.
_crypt_ctx = None  # type: ignore
_USE_PASSLIB = False
try:
    from passlib.context import CryptContext  # type: ignore

    _crypt_ctx_candidate = CryptContext(schemes=["bcrypt"], deprecated="auto")
    # Verify the backend actually works (Python 3.12+ bcrypt incompatibilities)
    _crypt_ctx_candidate.hash("probe")
    _crypt_ctx = _crypt_ctx_candidate
    _USE_PASSLIB = True
except Exception:
    _crypt_ctx = None
    _USE_PASSLIB = False


def _hash_password(password: str) -> str:
    if _USE_PASSLIB:
        return _crypt_ctx.hash(password)
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERS)
    return f"pbkdf2${salt}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    if _USE_PASSLIB and not stored.startswith("pbkdf2$"):
        return _crypt_ctx.verify(password, stored)
    try:
        _, salt, dk_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERS)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id       TEXT PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    hashed_pw     TEXT NOT NULL,
    role          TEXT NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    REAL NOT NULL,
    last_login    REAL
);
"""

# Default admin account seeded on first startup
_DEFAULT_ADMIN_USERNAME = "admin"
_DEFAULT_ADMIN_PASSWORD_ENV = "BONBON_ADMIN_PASSWORD"


class AuthManager:
    """Manage users and issue JWT access tokens.

    Parameters
    ----------
    db_path:
        Path to the SQLite users database.
    jwt_secret:
        Secret key for JWT signing.  Must come from config/env.
    algorithm:
        JWT signing algorithm (default HS256).
    token_expire_minutes:
        Token lifetime in minutes.
    """

    def __init__(
        self,
        db_path: Path,
        jwt_secret: str,
        algorithm: str = "HS256",
        token_expire_minutes: int = 60,
    ) -> None:
        if not jwt_secret:
            raise ValueError("jwt_secret must not be empty")
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._secret = jwt_secret
        self._algorithm = algorithm
        self._expire_minutes = token_expire_minutes
        self._init_db()

    # ------------------------------------------------------------------
    # DB setup
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute(_SCHEMA)
            conn.commit()
        # Seed default admin if no users exist
        self._seed_default_admin()

    def _seed_default_admin(self) -> None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM users;").fetchone()
            if row[0] == 0:
                pw = os.environ.get(_DEFAULT_ADMIN_PASSWORD_ENV, "")
                if not pw:
                    if os.environ.get("BONBON_TEST_MODE", "0") == "1":
                        pw = "BonBon-test-admin-only!"
                    else:
                        raise ValueError(
                            f"{_DEFAULT_ADMIN_PASSWORD_ENV} must be set before "
                            "the first operator API startup."
                        )
                self.create_user(
                    UserCreate(
                        username=_DEFAULT_ADMIN_USERNAME,
                        password=pw,
                        role="admin",
                    )
                )
                logger.warning(
                    "Default admin account created. " "Password came from %s.",
                    _DEFAULT_ADMIN_PASSWORD_ENV,
                )

    # ------------------------------------------------------------------
    # User CRUD
    # ------------------------------------------------------------------

    def create_user(self, req: UserCreate) -> UserInfo:
        if req.role not in VALID_ROLES:
            raise ValueError(f"Invalid role: {req.role}")
        user_id = str(uuid.uuid4())
        hashed = _hash_password(req.password)
        with self._get_conn() as conn:
            try:
                conn.execute(
                    "INSERT INTO users (user_id, username, hashed_pw, role, created_at) "
                    "VALUES (?,?,?,?,?);",
                    (user_id, req.username, hashed, req.role, time.time()),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                raise ValueError(f"Username '{req.username}' already exists") from None
        return UserInfo(user_id=user_id, username=req.username, role=req.role, is_active=True)

    def get_user_by_username(self, username: str) -> dict | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE username = ?;", (username,)).fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, user_id: str) -> dict | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?;", (user_id,)).fetchone()
        return dict(row) if row else None

    def list_users(self) -> list:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT user_id, username, role, is_active, created_at, last_login FROM users;"
            ).fetchall()
        return [dict(r) for r in rows]

    def update_user(self, user_id: str, req: UserUpdate) -> UserInfo | None:
        user = self.get_user_by_id(user_id)
        if not user:
            return None
        updates = []
        params = []
        if req.role is not None:
            if req.role not in VALID_ROLES:
                raise ValueError(f"Invalid role: {req.role}")
            updates.append("role = ?")
            params.append(req.role)
        if req.is_active is not None:
            updates.append("is_active = ?")
            params.append(int(req.is_active))
        if req.password is not None:
            updates.append("hashed_pw = ?")
            params.append(_hash_password(req.password))
        if not updates:
            return UserInfo(**{k: user[k] for k in ("user_id", "username", "role", "is_active")})
        params.append(user_id)
        sql = f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?;"
        with self._get_conn() as conn:
            conn.execute(sql, params)
            conn.commit()
        updated = self.get_user_by_id(user_id)
        return UserInfo(
            user_id=updated["user_id"],
            username=updated["username"],
            role=updated["role"],
            is_active=bool(updated["is_active"]),
        )

    def delete_user(self, user_id: str) -> bool:
        with self._get_conn() as conn:
            cur = conn.execute("DELETE FROM users WHERE user_id = ?;", (user_id,))
            conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def authenticate(self, username: str, password: str) -> dict | None:
        """Return the user record if credentials are valid, else None."""
        user = self.get_user_by_username(username)
        if not user or not user["is_active"]:
            return None
        if not _verify_password(password, user["hashed_pw"]):
            return None
        # Update last_login
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET last_login = ? WHERE user_id = ?;",
                (time.time(), user["user_id"]),
            )
            conn.commit()
        return user

    def create_token(self, user: dict) -> tuple[str, int]:
        """Return (access_token, expires_in_seconds)."""
        now = int(time.time())
        exp = now + self._expire_minutes * 60
        payload = {
            "sub": user["user_id"],
            "username": user["username"],
            "role": user["role"],
            "iat": now,
            "exp": exp,
        }
        token = jwt.encode(payload, self._secret, algorithm=self._algorithm)
        return token, self._expire_minutes * 60

    def decode_token(self, token: str) -> TokenPayload:
        """Decode and validate a JWT.  Raises jwt.exceptions on failure."""
        payload = jwt.decode(token, self._secret, algorithms=[self._algorithm])
        return TokenPayload(**payload)
