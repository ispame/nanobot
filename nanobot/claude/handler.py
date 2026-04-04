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
        self._enabled = config.enabled  # Master switch for Claude Code (default off)

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

            # Nanobot built-in commands that should NOT be forwarded to Claude Code
            NANOBOT_COMMANDS = {"/claude", "/session", "/new", "/list", "/switch", "/close", "/closeall", "/help"}

            # Handle Claude Code built-in / commands - forward to Claude Code
            # All / commands EXCEPT nanobot built-ins are forwarded to Claude Code
            if command.startswith("/") and command not in NANOBOT_COMMANDS and not command.startswith("/session"):
                # Forward to Claude Code as a regular message
                return await self._forward_to_claude(
                    sender_id, content, channel, chat_id, on_progress
                )

            # Handle session commands (e.g., /session new, /session list)
            response = await self.router.handle_command(sender_id, command, args)

            await self.bus.publish_outbound(OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=response,
            ))
            return True

        return await self._forward_to_claude(
            sender_id, content, channel, chat_id, on_progress
        )

    async def _forward_to_claude(
        self,
        sender_id: str,
        content: str,
        channel: str,
        chat_id: str,
        on_progress: Callable[[str], None] | None = None,
    ) -> bool:
        """Forward a message to Claude Code."""
        if not self._enabled:
            logger.info("Claude Code is disabled, ignoring message")
            return False

        logger.info(f"Forwarding to Claude Code: user={sender_id}, content={content[:50]}...")
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

    async def _handle_mode_command(
        self,
        user_id: str,
        mode: str,
        args: str | None,
        channel: str,
        chat_id: str,
    ) -> bool:
        """Handle Claude Code mode switching commands."""
        session_id = self.router.get_user_session_id(user_id)
        if not session_id:
            await self.bus.publish_outbound(OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content="❌ 没有活动的会话，请先发送消息创建会话",
            ))
            return True

        session = self.router._sessions.get(session_id)
        if not session or not session.is_active:
            await self.bus.publish_outbound(OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content="❌ 会话已失效，请创建新会话",
            ))
            return True

        try:
            if mode == "plan":
                # Enter plan mode - just forward the /plan command
                response = await self.router.send_message(user_id, "/plan")
                await self.bus.publish_outbound(OutboundMessage(
                    channel=channel,
                    chat_id=chat_id,
                    content=response,
                ))
            elif mode == "one":
                # Single turn mode - send as message to Claude Code
                response = await self.router.send_message(user_id, "--one")
                await self.bus.publish_outbound(OutboundMessage(
                    channel=channel,
                    chat_id=chat_id,
                    content=response,
                ))
            elif mode == "auto":
                # Auto mode
                response = await self.router.send_message(user_id, "/auto")
                await self.bus.publish_outbound(OutboundMessage(
                    channel=channel,
                    chat_id=chat_id,
                    content=response,
                ))
            elif mode == "auto-approve":
                # Auto approve mode
                response = await self.router.send_message(user_id, "/auto-approve on")
                await self.bus.publish_outbound(OutboundMessage(
                    channel=channel,
                    chat_id=chat_id,
                    content=response,
                ))
            elif mode == "bypass":
                # Bypass permissions - use control request
                if session._process:
                    result = await session._process.send_control_request({
                        "subtype": "permission_bypass",
                    })
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=channel,
                        chat_id=chat_id,
                        content=f"✅ 已启用权限绕过模式",
                    ))
                else:
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=channel,
                        chat_id=chat_id,
                        content="❌ 无法执行，进程未启动",
                    ))
            elif mode == "default":
                # Reset to default mode
                if session._process:
                    result = await session._process.send_control_request({
                        "subtype": "reset_settings",
                    })
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=channel,
                        chat_id=chat_id,
                        content="✅ 已恢复默认设置",
                    ))
                else:
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=channel,
                        chat_id=chat_id,
                        content="❌ 无法执行，进程未启动",
                    ))
            else:
                await self.bus.publish_outbound(OutboundMessage(
                    channel=channel,
                    chat_id=chat_id,
                    content=f"未知模式: {mode}",
                ))
            return True
        except Exception as e:
            logger.error(f"Error handling mode command: {e}")
            await self.bus.publish_outbound(OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=f"❌ 执行失败: {str(e)}",
            ))
            return True

    async def close(self) -> None:
        """Clean up resources."""
        await self.router.close_all()
