"""Nanobot Web Chat Application"""

import json
import os
from pathlib import Path
from typing import Optional

# Global config
_config: Optional[dict] = None


def get_config() -> dict:
    """Get application configuration."""
    global _config
    if _config is None:
        config_json = os.environ.get("NANOBOT_WEB_CONFIG")
        if config_json:
            _config = json.loads(config_json)
        else:
            # Try to load from default location
            config_path = Path(__file__).parent.parent / "config.json"
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    _config = json.load(f)
            else:
                _config = {}
    return _config


def get_users_dir() -> Path:
    """Get users directory path."""
    config = get_config()
    users_dir = Path(__file__).parent.parent / "users"
    users_dir.mkdir(exist_ok=True)
    return users_dir


def get_user_dir(user_id: str) -> Path:
    """Get a specific user's directory."""
    users_dir = get_users_dir()
    user_dir = users_dir / user_id
    user_dir.mkdir(exist_ok=True)
    return user_dir


def get_user_memory_dir(user_id: str) -> Path:
    """Get user's memory directory."""
    user_dir = get_user_dir(user_id)
    memory_dir = user_dir / "memory"
    memory_dir.mkdir(exist_ok=True)
    return memory_dir


def get_user_sessions_dir(user_id: str) -> Path:
    """Get user's sessions directory."""
    user_dir = get_user_dir(user_id)
    sessions_dir = user_dir / "sessions"
    sessions_dir.mkdir(exist_ok=True)
    return sessions_dir


def get_shared_skills_dir() -> Path:
    """Get shared skills directory."""
    shared_dir = Path(__file__).parent.parent / "shared_skills"
    shared_dir.mkdir(exist_ok=True)
    return shared_dir


def get_nanobot_config() -> dict:
    """Get nanobot configuration."""
    config = get_config()
    nanobot_config = config.get("nanobot", {})

    # Expand paths
    if "config_path" in nanobot_config:
        nanobot_config["config_path"] = Path(
            nanobot_config["config_path"].replace("~", str(Path.home()))
        )
    if "workspace_path" in nanobot_config:
        nanobot_config["workspace_path"] = Path(
            nanobot_config["workspace_path"].replace("~", str(Path.home()))
        )

    return nanobot_config
