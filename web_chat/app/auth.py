"""Authentication system for Nanobot Web Chat"""

import hashlib
import secrets
import json
from pathlib import Path
from typing import Optional

from app import get_config, get_user_dir


class AuthError(Exception):
    """Authentication error."""
    pass


def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    """Hash a password with a random salt."""
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100000,
    )
    return hashed.hex(), salt


def verify_password(password: str, hashed: str, salt: str) -> bool:
    """Verify a password against its hash."""
    new_hash, _ = hash_password(password, salt)
    return new_hash == hashed


def get_allowed_ids() -> list[str]:
    """Get list of allowed user IDs."""
    config = get_config()
    return config.get("allowed_ids", [])


def get_admin_ids() -> list[str]:
    """Get list of admin IDs."""
    config = get_config()
    return config.get("admin_ids", [])


def is_allowed_id(user_id: str) -> bool:
    """Check if user ID is allowed to register."""
    allowed = get_allowed_ids()
    if not allowed:  # If empty, allow all
        return True
    return user_id in allowed


def is_admin(user_id: str) -> bool:
    """Check if user is an admin."""
    return user_id in get_admin_ids()


def get_user_data(user_id: str) -> Optional[dict]:
    """Get user data from storage."""
    user_dir = get_user_dir(user_id)
    user_file = user_dir / "user.json"
    if not user_file.exists():
        return None
    with open(user_file, "r", encoding="utf-8") as f:
        return json.load(f)


def save_user_data(user_id: str, data: dict) -> None:
    """Save user data to storage."""
    user_dir = get_user_dir(user_id)
    user_file = user_dir / "user.json"
    with open(user_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def register_user(user_id: str, password: str) -> bool:
    """Register a new user."""
    # Check if user already exists
    if get_user_data(user_id) is not None:
        raise AuthError("User already exists")

    # Check if ID is allowed
    if not is_allowed_id(user_id):
        raise AuthError("User ID not allowed to register")

    # Hash password
    hashed, salt = hash_password(password)

    # Save user data
    save_user_data(user_id, {
        "user_id": user_id,
        "password_hash": hashed,
        "salt": salt,
        "is_admin": is_admin(user_id),
    })

    # Initialize user files
    _initialize_user_files(user_id)

    return True


def authenticate(user_id: str, password: str) -> bool:
    """Authenticate a user."""
    user_data = get_user_data(user_id)
    if user_data is None:
        return False

    return verify_password(
        password,
        user_data["password_hash"],
        user_data["salt"]
    )


def _initialize_user_files(user_id: str) -> None:
    """Initialize user's memory and soul files."""
    from app import get_user_memory_dir, get_user_dir

    user_dir = get_user_dir(user_id)
    memory_dir = get_user_memory_dir(user_id)

    # Create soul.md if not exists
    soul_file = user_dir / "soul.md"
    if not soul_file.exists():
        soul_file.write_text(
            f"# {user_id}'s Soul\n\n"
            f"This is {user_id}'s personal AI assistant.\n\n"
            "## Preferences\n\n- Communication style: [Describe your preferences]\n- Interests: [List your interests]\n- Background: [Your background info]\n",
            encoding="utf-8"
        )

    # Create MEMORY.md if not exists
    memory_file = memory_dir / "MEMORY.md"
    if not memory_file.exists():
        memory_file.write_text(
            f"# {user_id}'s Long-term Memory\n\n"
            f"This is {user_id}'s persistent memory.\n",
            encoding="utf-8"
        )

    # Create HISTORY.md if not exists
    history_file = memory_dir / "HISTORY.md"
    if not history_file.exists():
        history_file.write_text(
            f"# {user_id}'s Conversation History\n\n",
            encoding="utf-8"
        )
