"""Session management for Claude Code."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger


@dataclass
class SessionMetadata:
    """Metadata for a Claude Code session."""

    session_id: str
    user_id: str
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)
    cwd: str = ""
    model: str = ""


class ClaudeSession:
    """Represents a Claude Code session for a user."""

    def __init__(
        self,
        session_id: str,
        user_id: str,
        cwd: str | None = None,
        model: str | None = None,
    ):
        self.session_id = session_id
        self.user_id = user_id
        self.cwd = cwd or ""
        self.model = model or ""
        self.metadata = SessionMetadata(
            session_id=session_id,
            user_id=user_id,
            cwd=cwd or "",
            model=model or "",
        )
        self.messages: list[dict[str, Any]] = []
        self._process = None  # ClaudeCodeProcess reference

    def attach_process(self, process) -> None:
        """Attach the Claude Code process to this session."""
        self._process = process

    @property
    def is_active(self) -> bool:
        """Check if session is active."""
        return self._process is not None

    def add_message(self, role: str, content: str, metadata: dict | None = None) -> None:
        """Add a message to the session history."""
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {},
        })
        self.metadata.last_active = datetime.now()

    def get_history(self) -> list[dict[str, Any]]:
        """Get session message history."""
        return self.messages

    def clear_history(self) -> None:
        """Clear session message history."""
        self.messages.clear()

    def to_dict(self) -> dict[str, Any]:
        """Convert session to dictionary for persistence."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "cwd": self.cwd,
            "model": self.model,
            "created_at": self.metadata.created_at.isoformat(),
            "last_active": self.metadata.last_active.isoformat(),
            "messages": self.messages,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClaudeSession":
        """Create session from dictionary."""
        session = cls(
            session_id=data["session_id"],
            user_id=data["user_id"],
            cwd=data.get("cwd", ""),
            model=data.get("model", ""),
        )
        session.messages = data.get("messages", [])
        if "created_at" in data:
            session.metadata.created_at = datetime.fromisoformat(data["created_at"])
        if "last_active" in data:
            session.metadata.last_active = datetime.fromisoformat(data["last_active"])
        return session


class SessionStore:
    """Persistent storage for Claude Code sessions."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_user_dir(self, user_id: str) -> Path:
        """Get the directory for a user's sessions."""
        user_dir = self.base_dir / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    def _get_session_file(self, user_id: str, session_id: str) -> Path:
        """Get the session file path."""
        return self._get_user_dir(user_id) / f"{session_id}.json"

    def save(self, session: ClaudeSession) -> None:
        """Save session to disk."""
        file_path = self._get_session_file(session.user_id, session.session_id)
        with open(file_path, "w") as f:
            json.dump(session.to_dict(), f, indent=2)
        logger.debug(f"Saved session {session.session_id} to {file_path}")

    def load(self, user_id: str, session_id: str) -> ClaudeSession | None:
        """Load session from disk."""
        file_path = self._get_session_file(user_id, session_id)
        if not file_path.exists():
            return None

        try:
            with open(file_path) as f:
                data = json.load(f)
            return ClaudeSession.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to load session {session_id}: {e}")
            return None

    def list_sessions(self, user_id: str) -> list[dict[str, Any]]:
        """List all sessions for a user."""
        user_dir = self._get_user_dir(user_id)
        sessions = []

        for file_path in user_dir.glob("*.json"):
            try:
                with open(file_path) as f:
                    data = json.load(f)
                sessions.append({
                    "session_id": data.get("session_id"),
                    "created_at": data.get("created_at"),
                    "last_active": data.get("last_active"),
                    "cwd": data.get("cwd", ""),
                    "model": data.get("model", ""),
                })
            except (json.JSONDecodeError, KeyError):
                continue

        # Sort by last_active descending
        sessions.sort(key=lambda x: x.get("last_active", ""), reverse=True)
        return sessions

    def delete(self, user_id: str, session_id: str) -> bool:
        """Delete a session."""
        file_path = self._get_session_file(user_id, session_id)
        if file_path.exists():
            file_path.unlink()
            return True
        return False
