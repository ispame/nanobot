"""Android remote control channel via WebSocket."""

import asyncio
import json
import base64
import uuid
from pathlib import Path
from typing import Any

from aiohttp import web
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel


class AndroidChannel(BaseChannel):
    """Android remote control channel with WebSocket and ASR support."""

    name = "android"

    def __init__(self, config: Any, bus: MessageBus):
        super().__init__(config, bus)
        self.host = config.host
        self.port = config.port
        self.asr_url = config.asr_url
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

    async def websocket_handler(self, request: web.Request) -> web.WebSocketResponse:
        """Handle WebSocket connections."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        client_id = str(uuid.uuid4())
        self.clients[client_id] = ws
        logger.info(f"Android client connected: {client_id}")

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

    async def _handle_ws_message(self, data: str, client_id: str) -> None:
        """Process incoming WebSocket message."""
        try:
            msg = json.loads(data)
            msg_type = msg.get("type")
            sender_id = msg.get("sender_id", client_id)

            if msg_type == "text":
                content = msg.get("content", "")
                await self._handle_message(sender_id, client_id, content)

            elif msg_type == "audio":
                audio_data = msg.get("audio_data", "")
                await self._process_audio(audio_data, sender_id, client_id)

        except Exception as e:
            logger.error(f"Error handling message: {e}")
            await self._send_error(client_id, str(e))

    async def _process_audio(self, audio_base64: str, sender_id: str, chat_id: str) -> None:
        """Process audio data with ASR."""
        try:
            # Decode base64 audio
            audio_data = base64.b64decode(audio_base64)

            # Save to temp file
            temp_file = self.temp_dir / f"{uuid.uuid4()}.wav"
            temp_file.write_bytes(audio_data)

            # Send processing status
            await self._send_status(chat_id, "processing")

            # Import and use ASR
            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "asr_demo"))
            from huoshan_sdk import AsrWsClient, config

            # Set ASR credentials from config
            config.auth = {
                "app_key": self.config.asr_app_id,  # app_key 实际上是 appId
                "access_key": self.config.asr_access_key
            }

            # Run ASR
            text_result = ""
            async with AsrWsClient(self.asr_url) as client:
                async for response in client.execute(str(temp_file)):
                    if response.payload_msg:
                        result = response.payload_msg.get('result', {})
                        if isinstance(result, dict):
                            text_result = result.get('text', '')
                        elif isinstance(result, str):
                            text_result = result

            # Clean up temp file
            temp_file.unlink(missing_ok=True)

            if text_result:
                await self._handle_message(sender_id, chat_id, text_result)
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
        except Exception as e:
            logger.error(f"Send error: {e}")

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

