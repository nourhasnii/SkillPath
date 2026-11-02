import logging
import os
import sqlite3

from .auth import PASSWORD_HASHER, validate_new_password, verify_password
from .auth_store import account_by_email, create_admin, update_admin

logger = logging.getLogger(__name__)
ADMIN_EMAIL = "nour.hasni02@gmail.com"
ADMIN_NAME = "Nour Hasni"
ADMIN_PASSWORD_ENV = "SKILLPATH_ADMIN_PASSWORD"


def seed_admin_account() -> None:
    environment = os.environ.get("ENVIRONMENT", "").strip().lower()
    print(f"Admin seeder: checking environment ({environment or 'unset'}).", flush=True)
    if environment != "development":
        logger.info("Admin seeder skipped: development mode is not active.")
        print("Admin seeder skipped: development mode is not active.", flush=True)
        return

    password = os.environ.get(ADMIN_PASSWORD_ENV)
    if not password:
        logger.warning(
            "Admin seeder skipped: configure %s in the local development environment.",
            ADMIN_PASSWORD_ENV,
        )
        print(f"Admin seeder skipped: {ADMIN_PASSWORD_ENV} is not configured.", flush=True)
        return

    logger.info(
        "Admin seeder: development password loaded from %s (value redacted).",
        ADMIN_PASSWORD_ENV,
    )
    print(
        f"Admin seeder: development password loaded from {ADMIN_PASSWORD_ENV} "
        "(value redacted).",
        flush=True,
    )

    try:
        validate_new_password(password)
    except ValueError as error:
        raise RuntimeError(
            f"{ADMIN_PASSWORD_ENV} must satisfy the password requirements."
        ) from error

    existing = account_by_email(ADMIN_EMAIL)
    password_hash = PASSWORD_HASHER.hash(password)
    if not verify_password(password_hash, password):
        raise RuntimeError("Admin bootstrap password hash verification failed.")
    logger.info("Admin seeder: Argon2id hash generated and verified.")
    print("Admin seeder: Argon2id hash generated and verified.", flush=True)

    try:
        if existing is None:
            create_admin(ADMIN_EMAIL, ADMIN_NAME, password_hash)
        else:
            update_admin(existing["id"], ADMIN_NAME, password_hash)
    except sqlite3.IntegrityError:
        concurrently_created = account_by_email(ADMIN_EMAIL)
        if concurrently_created is None:
            raise
        update_admin(concurrently_created["id"], ADMIN_NAME, password_hash)
        existing = concurrently_created

    result = "Admin créé avec succès" if existing is None else "Admin mis à jour avec succès"
    logger.info("%s (email: %s)", result, ADMIN_EMAIL)
    print(result, flush=True)
    print(f"Email : {ADMIN_EMAIL}", flush=True)
