import hashlib
import os
import secrets
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

_schema_lock = threading.Lock()
_schema_ready: set[str] = set()


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exception_type, exception, traceback):
        try:
            return super().__exit__(exception_type, exception, traceback)
        finally:
            self.close()


@dataclass(frozen=True)
class Account:
    id: str
    email: str
    full_name: str
    role: str
    profile_iri: str | None
    experience: str


def database_path() -> str:
    configured = os.environ.get("AUTH_DATABASE_PATH")
    if configured:
        return str(Path(configured).expanduser().resolve())
    return str(Path(__file__).resolve().parent.parent / "data" / "auth.sqlite3")


def _connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10, isolation_level=None, factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def initialize_store() -> None:
    path = database_path()
    if path in _schema_ready:
        return
    with _schema_lock:
        if path in _schema_ready:
            return
        connection = _connect(path)
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    full_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('STUDENT', 'PROFESSIONAL', 'ADMIN')),
                    profile_iri TEXT UNIQUE,
                    experience TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    expires_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS auth_sessions_expiry ON auth_sessions(expires_at);
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    token_hash TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    expires_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS reset_tokens_expiry ON password_reset_tokens(expires_at);
                CREATE TABLE IF NOT EXISTS login_attempts (
                    bucket TEXT PRIMARY KEY,
                    failures INTEGER NOT NULL,
                    window_started_at INTEGER NOT NULL,
                    blocked_until INTEGER NOT NULL DEFAULT 0
                );
                """
            )
        finally:
            connection.close()
        _schema_ready.add(path)


def connect() -> sqlite3.Connection:
    initialize_store()
    return _connect(database_path())


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def new_reset_token() -> str:
    return secrets.token_urlsafe(32)


def account_from_row(row: sqlite3.Row) -> Account:
    return Account(
        id=row["id"],
        email=row["email"],
        full_name=row["full_name"],
        role=row["role"],
        profile_iri=row["profile_iri"],
        experience=row["experience"],
    )


def account_by_id(account_id: str) -> Account | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT id, email, full_name, role, profile_iri, experience "
            "FROM accounts WHERE id = ?",
            (account_id,),
        ).fetchone()
    return account_from_row(row) if row else None


def account_by_email(email: str) -> sqlite3.Row | None:
    with connect() as connection:
        return connection.execute(
            "SELECT * FROM accounts WHERE email = ? COLLATE NOCASE",
            (email,),
        ).fetchone()


def account_for_session(raw_token: str, now: int | None = None) -> Account | None:
    current_time = int(time.time()) if now is None else now
    token_hash = hash_secret(raw_token)
    with connect() as connection:
        row = connection.execute(
            """
            SELECT a.id, a.email, a.full_name, a.role, a.profile_iri, a.experience
            FROM auth_sessions AS s
            JOIN accounts AS a ON a.id = s.account_id
            WHERE s.token_hash = ? AND s.expires_at > ?
            """,
            (token_hash, current_time),
        ).fetchone()
        connection.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (current_time,))
    return account_from_row(row) if row else None


def create_session(account_id: str, lifetime_seconds: int) -> str:
    raw_token = new_session_token()
    now = int(time.time())
    with connect() as connection:
        connection.execute(
            "INSERT INTO auth_sessions(token_hash, account_id, expires_at, created_at) "
            "VALUES (?, ?, ?, ?)",
            (hash_secret(raw_token), account_id, now + lifetime_seconds, now),
        )
    return raw_token


def revoke_session(raw_token: str) -> None:
    with connect() as connection:
        connection.execute(
            "DELETE FROM auth_sessions WHERE token_hash = ?",
            (hash_secret(raw_token),),
        )


def revoke_account_sessions(account_id: str) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM auth_sessions WHERE account_id = ?", (account_id,))


def store_reset_token(account_id: str, raw_token: str, lifetime_seconds: int) -> None:
    now = int(time.time())
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM password_reset_tokens WHERE account_id = ?", (account_id,))
        connection.execute(
            "INSERT INTO password_reset_tokens(token_hash, account_id, expires_at, created_at) "
            "VALUES (?, ?, ?, ?)",
            (hash_secret(raw_token), account_id, now + lifetime_seconds, now),
        )
        connection.commit()


def update_password_from_reset(raw_token: str, password_hash: str) -> str | None:
    now = int(time.time())
    token_hash = hash_secret(raw_token)
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT account_id FROM password_reset_tokens "
            "WHERE token_hash = ? AND expires_at > ?",
            (token_hash, now),
        ).fetchone()
        if not row:
            connection.execute(
                "DELETE FROM password_reset_tokens WHERE expires_at <= ?", (now,)
            )
            connection.commit()
            return None
        account_id = row["account_id"]
        connection.execute(
            "UPDATE accounts SET password_hash = ? WHERE id = ?",
            (password_hash, account_id),
        )
        connection.execute("DELETE FROM password_reset_tokens WHERE account_id = ?", (account_id,))
        connection.execute("DELETE FROM auth_sessions WHERE account_id = ?", (account_id,))
        connection.commit()
    return account_id


def create_account(
    email: str,
    full_name: str,
    password_hash: str,
    role: str,
    profile_iri: str,
) -> Account:
    now = int(time.time())
    account_id = str(uuid.uuid4())
    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO accounts(id, email, full_name, password_hash, role, profile_iri, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (account_id, email, full_name, password_hash, role, profile_iri, now),
        )
        connection.commit()
    except sqlite3.IntegrityError:
        connection.rollback()
        raise
    finally:
        connection.close()
    account = account_by_id(account_id)
    if account is None:
        raise RuntimeError("Account insert did not produce a readable row.")
    return account


def create_admin(email: str, full_name: str, password_hash: str) -> Account:
    now = int(time.time())
    account_id = str(uuid.uuid4())
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO accounts(id, email, full_name, password_hash, role, created_at)
            VALUES (?, ?, ?, ?, 'ADMIN', ?)
            """,
            (account_id, email, full_name, password_hash, now),
        )
    account = account_by_id(account_id)
    if account is None:
        raise RuntimeError("Admin insert did not produce a readable row.")
    return account


def update_admin(account_id: str, full_name: str, password_hash: str) -> Account:
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """
            UPDATE accounts
            SET full_name = ?, password_hash = ?, role = 'ADMIN',
                profile_iri = NULL, experience = ''
            WHERE id = ?
            """,
            (full_name, password_hash, account_id),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            raise RuntimeError("Admin account disappeared while updating bootstrap credentials.")
        connection.execute("DELETE FROM auth_sessions WHERE account_id = ?", (account_id,))
        connection.commit()
    account = account_by_id(account_id)
    if account is None:
        raise RuntimeError("Admin account disappeared after bootstrap update.")
    return account


def update_account_profile(
    account_id: str, full_name: str, experience: str
) -> Account:
    with connect() as connection:
        connection.execute(
            "UPDATE accounts SET full_name = ?, experience = ? WHERE id = ?",
            (full_name, experience, account_id),
        )
    account = account_by_id(account_id)
    if account is None:
        raise RuntimeError("Account disappeared while updating its profile.")
    return account


def set_account_role(account_id: str, role: str) -> None:
    with connect() as connection:
        connection.execute("UPDATE accounts SET role = ? WHERE id = ?", (role, account_id))


def list_accounts() -> list[Account]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT id, email, full_name, role, profile_iri, experience "
            "FROM accounts ORDER BY created_at DESC"
        ).fetchall()
    return [account_from_row(row) for row in rows]


def login_bucket(email: str, client_ip: str) -> str:
    return hash_secret(f"{email.lower()}|{client_ip}")


def login_is_blocked(bucket: str, now: int | None = None) -> bool:
    current = int(time.time()) if now is None else now
    with connect() as connection:
        row = connection.execute(
            "SELECT blocked_until FROM login_attempts WHERE bucket = ?", (bucket,)
        ).fetchone()
    return bool(row and row["blocked_until"] > current)


def record_login_failure(bucket: str, now: int | None = None) -> None:
    current = int(time.time()) if now is None else now
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT failures, window_started_at FROM login_attempts WHERE bucket = ?",
            (bucket,),
        ).fetchone()
        if not row or current - row["window_started_at"] > 900:
            failures, window_started = 1, current
        else:
            failures, window_started = row["failures"] + 1, row["window_started_at"]
        blocked_until = current + 900 if failures >= 8 else 0
        connection.execute(
            """
            INSERT INTO login_attempts(bucket, failures, window_started_at, blocked_until)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(bucket) DO UPDATE SET
                failures = excluded.failures,
                window_started_at = excluded.window_started_at,
                blocked_until = excluded.blocked_until
            """,
            (bucket, failures, window_started, blocked_until),
        )
        connection.commit()


def clear_login_failures(bucket: str) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM login_attempts WHERE bucket = ?", (bucket,))


def reset_token_account(raw_token: str) -> str | None:
    now = int(time.time())
    with connect() as connection:
        row = connection.execute(
            "SELECT account_id FROM password_reset_tokens "
            "WHERE token_hash = ? AND expires_at > ?",
            (hash_secret(raw_token), now),
        ).fetchone()
    return row["account_id"] if row else None


def delete_account(account_id: str) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM accounts WHERE id = ?", (account_id,))


def delete_reset_tokens(account_id: str) -> None:
    with connect() as connection:
        connection.execute(
            "DELETE FROM password_reset_tokens WHERE account_id = ?", (account_id,)
        )


def bind_profile(account_id: str, profile_iri: str) -> None:
    with connect() as connection:
        cursor = connection.execute(
            "UPDATE accounts SET profile_iri = ? WHERE id = ?",
            (profile_iri, account_id),
        )
    if cursor.rowcount != 1:
        raise RuntimeError("Account disappeared while linking its ontology profile.")
