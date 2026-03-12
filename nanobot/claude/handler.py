"""Message handler for Claude Code integration with channels."""

import asyncio

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

    def is_command(self, content: str) -> bool:
        """Check if message is a command."""
        return content.strip().startswith("/")

    async def handle_message(
        self,
        sender_id: str,
        content: str,
        channel: str,
        chat_id: str,
        on_progress: callable | None = None,
    ) -> bool:
        """Handle an incoming message.

        Returns True if message was handled (command or Claude Code response).
        """
        # Check if it's a command
        if self.is_command(content):
            parts = content.strip().split(maxsplit=1)
            command = parts[0]
            args = parts[1] if len(parts) > 1 else None

            response = await self.router.handle_command(sender_id, command, args)

            await self.bus.publish_outbound(OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=response,
            ))
            return True

        # Send to Claude Code
        try:
            response = await self.router.send_message(
                sender_id,
                content,
                on_progress=on_progress,
            )

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
