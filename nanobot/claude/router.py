"""Message router for Claude Code sessions."""

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.claude.client import ClaudeClient
from nanobot.claude.session import ClaudeSession, SessionStore

if TYPE_CHECKING:
    from nanobot.config.schema import ClaudeCodeConfig


class SessionRouter:
    """Routes messages between chat channels and Claude Code sessions."""

    def __init__(
        self,
        config: "ClaudeCodeConfig",
        bus: MessageBus,
        session_store: SessionStore,
    ):
        self.config = config
        self.bus = bus
        self.session_store = session_store
        self.client = ClaudeClient(config)

        # user_id -> current_session_id mapping
        self._user_sessions: dict[str, str] = {}
        # session_id -> ClaudeSession
        self._sessions: dict[str, ClaudeSession] = {}

    def get_user_session_id(self, user_id: str) -> str | None:
        """Get the current session ID for a user."""
        return self._user_sessions.get(user_id)

    def set_user_session_id(self, user_id: str, session_id: str) -> None:
        """Set the current session for a user."""
        self._user_sessions[user_id] = session_id

    async def create_session(
        self, user_id: str, cwd: str | None = None
    ) -> ClaudeSession:
        """Create a new Claude Code session for a user."""
        # Check max sessions limit
        existing = self.session_store.list_sessions(user_id)
        if len(existing) >= self.config.max_sessions_per_user:
            raise ValueError(
                f"Maximum sessions ({self.config.max_sessions_per_user}) reached"
            )

        session_id = f"nanobot_{user_id}_{len(existing) + 1}"
        session = ClaudeSession(
            session_id=session_id,
            user_id=user_id,
            cwd=cwd,
            model=self.config.default_model,
        )

        # Create Claude Code process
        process = await self.client.create_session(session_id=session_id, cwd=cwd)
        session.attach_process(process)

        # Save to store
        self.session_store.save(session)

        # Track in memory
        self._sessions[session_id] = session
        self._user_sessions[user_id] = session_id

        logger.info(f"Created new session {session_id} for user {user_id}")
        return session

    async def switch_session(self, user_id: str, session_id: str) -> bool:
        """Switch to an existing session."""
        # Check if session exists
        session = self._sessions.get(session_id)
        if not session:
            session = self.session_store.load(user_id, session_id)
            if not session:
                return False
            # Re-attach process if needed
            self._sessions[session_id] = session

        self._user_sessions[user_id] = session_id
        logger.info(f"Switched user {user_id} to session {session_id}")
        return True

    async def close_session(self, user_id: str, session_id: str | None = None) -> bool:
        """Close a session."""
        if session_id is None:
            session_id = self._user_sessions.get(user_id)

        if not session_id:
            return False

        # Close Claude Code process
        await self.client.close_session(session_id)

        # Remove from memory
        if session_id in self._sessions:
            del self._sessions[session_id]

        # Clear user mapping if it was the current session
        if self._user_sessions.get(user_id) == session_id:
            del self._user_sessions[user_id]

        # Delete from store
        self.session_store.delete(user_id, session_id)

        logger.info(f"Closed session {session_id}")
        return True

    def list_sessions(self, user_id: str) -> list[dict]:
        """List all sessions for a user."""
        return self.session_store.list_sessions(user_id)

    async def send_message(
        self,
        user_id: str,
        content: str,
        on_progress: callable | None = None,
    ) -> str:
        """Send a message to Claude Code and return the response."""
        # Get or create session
        session_id = self._user_sessions.get(user_id)
        if not session_id:
            session = await self.create_session(user_id)
            session_id = session.session_id
        else:
            session = self._sessions.get(session_id)

        if not session or not session.is_active:
            # Try to resume or create new
            session = await self.create_session(user_id)
            session_id = session.session_id

        # Add to history
        session.add_message("user", content)

        # Stream response from Claude Code
        response_parts = []
        process = session._process

        async for event in process.send_message(content):
            msg_type = event.get("type")

            if msg_type == "content":
                # Text content
                content_block = event.get("content", [])
                if isinstance(content_block, list):
                    for block in content_block:
                        if block.get("type") == "text":
                            text = block.get("text", "")
                            response_parts.append(text)
                            if on_progress:
                                on_progress(text)
                elif isinstance(content_block, dict):
                    if content_block.get("type") == "text":
                        text = content_block.get("text", "")
                        response_parts.append(text)
                        if on_progress:
                            on_progress(text)

            elif msg_type == "progress":
                # Progress message
                if on_progress:
                    on_progress(event.get("message", ""))

        response = "".join(response_parts)
        session.add_message("assistant", response)

        # Save session
        self.session_store.save(session)

        return response

    async def handle_command(
        self, user_id: str, command: str, args: str | None = None
    ) -> str:
        """Handle a session management command."""
        cmd = command.lower().strip()

        if cmd == "new":
            # Create new session
            try:
                session = await self.create_session(user_id)
                return f"✅ 已创建新会话 #{session.session_id.split('_')[-1]}"
            except ValueError as e:
                return f"❌ {str(e)}"

        elif cmd == "list":
            # List sessions
            sessions = self.list_sessions(user_id)
            if not sessions:
                return "暂无会话记录"

            current = self._user_sessions.get(user_id)
            lines = ["会话列表:"]
            for i, s in enumerate(sessions, 1):
                marker = " (当前)" if s["session_id"] == current else ""
                lines.append(f"{i}. {s['session_id']}{marker}")
            return "\n".join(lines)

        elif cmd == "switch" and args:
            # Switch session
            # Find session by number or ID
            sessions = self.list_sessions(user_id)
            session_id = None

            # Try by number
            try:
                idx = int(args) - 1
                if 0 <= idx < len(sessions):
                    session_id = sessions[idx]["session_id"]
            except ValueError:
                pass

            # Try by ID
            if not session_id:
                for s in sessions:
                    if args in s["session_id"]:
                        session_id = s["session_id"]
                        break

            if session_id:
                success = await self.switch_session(user_id, session_id)
                if success:
                    return f"✅ 已切换到会话 {session_id.split('_')[-1]}"
                return "❌ 切换失败，会话不存在"

            return "❌ 会话不存在"

        elif cmd == "close":
            # Close current session
            success = await self.close_session(user_id)
            if success:
                return "✅ 已关闭当前会话"
            return "❌ 没有活动的会话"

        elif cmd == "help":
            # Show help
            return """Claude Code 命令:
/new - 创建新会话
/list - 列出所有会话
/switch <id> - 切换会话
/close - 关闭当前会话
/help - 显示帮助"""

        return f"未知命令: {command}"

    async def close_all(self) -> None:
        """Close all sessions."""
        await self.client.close_all()
        self._sessions.clear()
        self._user_sessions.clear()
