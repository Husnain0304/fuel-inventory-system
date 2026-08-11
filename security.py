import hashlib
import hmac
import re

import bcrypt


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,40}$")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, stored_hash: str) -> tuple[bool, bool]:
    """Return (valid, needs_upgrade), supporting legacy SHA-256 accounts."""
    if not stored_hash:
        return False, False
    if stored_hash.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8")), False
        except ValueError:
            return False, False
    legacy = hashlib.sha256(password.encode("utf-8")).hexdigest()
    valid = hmac.compare_digest(legacy, stored_hash)
    return valid, valid


def validate_password(password: str) -> str | None:
    if len(password) < 10:
        return "Use at least 10 characters."
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        return "Include at least one letter and one number."
    return None


def validate_username(username: str) -> str | None:
    if not USERNAME_PATTERN.fullmatch(username):
        return "Use 3-40 letters, numbers, dots, dashes, or underscores."
    return None
