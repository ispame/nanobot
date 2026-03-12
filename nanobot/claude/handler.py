"""Message handler for Claude Code integration with channels."""

import asyncio
from typing import Callable

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.claude.router import SessionRouter
from nanobot.config.schema import ClaudeCodeConfig


class ClaudeMessageHandler:
    """Handles messages between chat channels and Claude Code."""

    def __init__(
        self,
        config: ClaudeCodeConfig,
        bus: MessageBus,
        router: SessionRouter,
    ):
        self.config = config
        self.bus = bus
        self.router = router
        self._enabled = True  # Master switch for Claude Code

    def is_enabled(self) -> bool:
        """Check if Claude Code is enabled."""
        return self._enabled

    def enable(self) -> None:
        """Enable Claude Code."""
        self._enabled = True
        logger.info("Claude Code enabled")

    def disable(self) -> None:
        """Disable Claude Code."""
        self._enabled = False
        logger.info("Claude Code disabled")

    def is_command(self, content: str) -> bool:
        """Check if message is a command."""
        stripped = content.strip()
        return stripped.startswith("/") or stripped.lower() in ("help", "?")

    async def handle_message(
        self,
        sender_id: str,
        content: str,
        channel: str,
        chat_id: str,
        on_progress: Callable[[str], None] | None = None,
    ) -> bool:
        """Handle an incoming message.

        Returns True if message was handled (command or Claude Code response).
        """
        # Check if it's a command
        logger.info(f"Content: '{content}', is_command: {self.is_command(content)}")
        if self.is_command(content):
            parts = content.strip().split(maxsplit=1)
            command = parts[0].lower()
            args = parts[1] if len(parts) > 1 else None

            # Handle /claude on/off commands
            if command == "/claude":
                if args and args.lower() in ("on", "enable", "开启"):
                    self.enable()
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=channel,
                        chat_id=chat_id,
                        content="✅ Claude Code 已开启",
                    ))
                    return True
                elif args and args.lower() in ("off", "disable", "关闭"):
                    self.disable()
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=channel,
                        chat_id=chat_id,
                        content="✅ Claude Code 已关闭",
                    ))
                    return True
                else:
                    status = "开启" if self._enabled else "关闭"
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=channel,
                        chat_id=chat_id,
                        content=f"Claude Code 当前状态: {status}\n用法: /claude on | off",
                    ))
                    return True

            # Handle session commands
            response = await self.router.handle_command(sender_id, command, args)

            await self.bus.publish_outbound(OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=response,
            ))
            return True

        # Check if Claude Code is enabled
        if not self._enabled:
            logger.info("Claude Code is disabled, ignoring message")
            return False

        # Send to Claude Code
        logger.info(f"Sending to Claude Code: user={sender_id}, content={content[:50]}...")
        try:
            response = await self.router.send_message(
                sender_id,
                content,
                on_progress=on_progress,
            )

            logger.info(f"Claude Code response received: {len(response)} chars")
            await self.bus.publish_outbound(OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=response,
            ))
            return True

        except Exception as e:
            logger.error(f"Error sending to Claude Code: {e}")
            await self.bus.publish_outbound(OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=f"抱歉，发生错误: {str(e)}",
            ))
            return True

    async def close(self) -> None:
        """Clean up resources."""
        await self.router.close_all()
