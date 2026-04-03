"""Android remote control channel via WebSocket."""

import asyncio
import json
import base64
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from aiohttp import web
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel

# 固定的 session key，所有 Android 设备共享同一个对话历史
ANDROID_SESSION_KEY = "android:default"


class AndroidChannel(BaseChannel):
    """Android remote control channel with WebSocket, ASR and history support."""

    name = "android"

    def __init__(self, config: Any, bus: MessageBus, session_manager=None):
        super().__init__(config, bus)
        self.host = config.host
        self.port = config.port
        self.asr_url = config.asr_url
        self.session_manager = session_manager
        self.history_days = getattr(config, "history_days", 10)
        self.history_page_size = getattr(config, "history_page_size", 10)
        self.clients: dict[str, web.WebSocketResponse] = {}
        self.runner = None
        self.temp_dir = Path("/tmp/nanobot_android")
        self.temp_dir.mkdir(exist_ok=True)

    async def start(self) -> None:
        """Start WebSocket server."""
        self._running = True

        app = web.Application()
        app.router.add_get('/ws', self.websocket_handler)

        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, self.host, self.port)
        await site.start()

        logger.info(f"Android channel started on ws://{self.host}:{self.port}/ws")

    async def stop(self) -> None:
        """Stop WebSocket server."""
        self._running = False

        for ws in self.clients.values():
            await ws.close()
        self.clients.clear()

        if self.runner:
            await self.runner.cleanup()

        logger.info("Android channel stopped")

    def _get_session(self):
        """Get or create the Android session."""
        if self.session_manager:
            return self.session_manager.get_or_create(ANDROID_SESSION_KEY)
        return None

    def _cleanup_old_messages(self, session) -> None:
        """Remove messages older than history_days."""
        cutoff = datetime.now() - timedelta(days=self.history_days)
        before = len(session.messages)
        session.messages = [
            m for m in session.messages
            if datetime.fromisoformat(m["timestamp"]) > cutoff
        ]
        if len(session.messages) < before:
            logger.debug("Cleaned {} old messages from android session", before - len(session.messages))

    async def websocket_handler(self, request: web.Request) -> web.WebSocketResponse:
        """Handle WebSocket connections."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        client_id = str(uuid.uuid4())
        self.clients[client_id] = ws
        logger.info(f"Android client connected: {client_id}")

        # 连接时发送最近 N 条历史
        await self._send_recent_history(ws)

        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    await self._handle_ws_message(msg.data, client_id)
                elif msg.type == web.WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {ws.exception()}")
        finally:
            self.clients.pop(client_id, None)
            logger.info(f"Android client disconnected: {client_id}")

        return ws

    async def _send_recent_history(self, ws: web.WebSocketResponse) -> None:
        """Send the most recent messages to the client on connect."""
        session = self._get_session()
        if not session:
            return

        cutoff = datetime.now() - timedelta(days=self.history_days)
        recent = [
            m for m in session.messages
            if datetime.fromisoformat(m["timestamp"]) > cutoff
        ][-self.history_page_size:]

        for msg in recent:
            await ws.send_json({
                "type": "history",
                "content": msg["content"],
                "role": msg["role"],
                "timestamp": msg["timestamp"],
            })

    async def _handle_ws_message(self, data: str, client_id: str) -> None:
        """Process incoming WebSocket message."""
        try:
            msg = json.loads(data)
            msg_type = msg.get("type")
            sender_id = msg.get("sender_id", client_id)

            if msg_type == "text":
                content = msg.get("content", "")
                logger.debug("Android received text: {!r}", content)
                self._save_user_message(content)
                await self._handle_message(sender_id, client_id, content,
                                           session_key=ANDROID_SESSION_KEY)

            elif msg_type == "audio":
                audio_data = msg.get("audio_data", "")
                await self._process_audio(audio_data, sender_id, client_id)

            elif msg_type == "load_history":
                await self._handle_load_history(msg, client_id)

        except Exception as e:
            logger.error(f"Error handling message: {e}")
            await self._send_error(client_id, str(e))

    async def _handle_load_history(self, msg: dict, client_id: str) -> None:
        """Handle load more history request."""
        ws = self.clients.get(client_id)
        if not ws or ws.closed:
            return

        before_timestamp = msg.get("before_timestamp")
        limit = msg.get("limit", self.history_page_size)

        session = self._get_session()
        if not session:
            await ws.send_json({"type": "history_page", "messages": [], "has_more": False})
            return

        cutoff = datetime.now() - timedelta(days=self.history_days)
        cutoff_str = cutoff.isoformat()

        # 获取 before_timestamp 之前的所有消息
        candidates = [
            m for m in session.messages
            if m["timestamp"] < before_timestamp and m["timestamp"] >= cutoff_str
        ][:limit]

        # 一次性发送整页，客户端 prepend 到列表顶部
        await ws.send_json({
            "type": "history_page",
            "messages": [
                {"content": m["content"], "role": m["role"], "timestamp": m["timestamp"]}
                for m in candidates
            ],
            "has_more": len(candidates) == limit,
        })

    def _save_user_message(self, content: str) -> None:
        """Save a user message to the session."""
        session = self._get_session()
        if not session:
            return
        session.add_message("user", content)
        self._cleanup_old_messages(session)
        self.session_manager.save(session)

    async def _process_audio(self, audio_base64: str, sender_id: str, chat_id: str) -> None:
        """Process audio data with ASR."""
        try:
            audio_data = base64.b64decode(audio_base64)
            temp_file = self.temp_dir / f"{uuid.uuid4()}.wav"
            temp_file.write_bytes(audio_data)

            await self._send_status(chat_id, "processing")

            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "asr_demo"))
            from huoshan_sdk import AsrWsClient, config

            config.auth = {
                "app_key": self.config.asr_app_id,
                "access_key": self.config.asr_access_key
            }

            text_result = ""
            async with AsrWsClient(self.asr_url) as client:
                async for response in client.execute(str(temp_file)):
                    if response.payload_msg:
                        result = response.payload_msg.get('result', {})
                        if isinstance(result, dict):
                            text_result = result.get('text', '')
                        elif isinstance(result, str):
                            text_result = result

            temp_file.unlink(missing_ok=True)

            if text_result:
                self._save_user_message(text_result)
                await self._handle_message(sender_id, chat_id, text_result,
                                           session_key=ANDROID_SESSION_KEY)
            else:
                await self._send_error(chat_id, "ASR failed")

        except Exception as e:
            logger.error(f"Audio processing error: {e}")
            await self._send_error(chat_id, f"Audio error: {e}")

    async def send(self, msg: OutboundMessage) -> None:
        """Send message to Android client."""
        ws = self.clients.get(msg.chat_id)
        if not ws or ws.closed:
            logger.warning(f"Client {msg.chat_id} not connected")
            return

        try:
            response = {
                "type": "message",
                "content": msg.content,
                "status": "done"
            }
            await ws.send_json(response)

            # 保存 assistant 回复到历史
            self._save_assistant_message(msg.content)

        except Exception as e:
            logger.error(f"Send error: {e}")

    def _save_assistant_message(self, content: str) -> None:
        """Save an assistant message to the session."""
        session = self._get_session()
        if not session:
            return
        session.add_message("assistant", content)
        self._cleanup_old_messages(session)
        self.session_manager.save(session)

    async def _send_status(self, chat_id: str, status: str) -> None:
        """Send status update to client."""
        ws = self.clients.get(chat_id)
        if ws and not ws.closed:
            await ws.send_json({"type": "status", "status": status})

    async def _send_error(self, chat_id: str, error: str) -> None:
        """Send error message to client."""
        ws = self.clients.get(chat_id)
        if ws and not ws.closed:
            await ws.send_json({"type": "status", "status": "error", "message": error})
