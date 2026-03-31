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

        # 流式录音支持
        self.audio_buffers: dict[str, bytearray] = {}          # client_id -> 累计音频
        self.audio_chunks: dict[str, list[bytes]] = {}          # client_id -> chunk列表(用于流式ASR)
        self.asr_streams: dict[str, Any] = {}                   # client_id -> AsrStreamer实例

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

        # 清理所有ASR流
        for streamer in self.asr_streams.values():
            try:
                await streamer.close()
            except Exception:
                pass
        self.asr_streams.clear()
        self.audio_buffers.clear()
        self.audio_chunks.clear()

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
            # 清理该客户端的资源
            self.clients.pop(client_id, None)
            self.audio_buffers.pop(client_id, None)
            self.audio_chunks.pop(client_id, None)
            streamer = self.asr_streams.pop(client_id, None)
            if streamer:
                try:
                    await streamer.close()
                except Exception:
                    pass
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

            # ─── 原有整体音频模式（向后兼容）───────────────────────────────
            elif msg_type == "audio":
                audio_data = msg.get("audio_data", "")
                await self._process_audio_batch(audio_data, sender_id, client_id)

            # ─── 新增：流式音频开始 ───────────────────────────────────────
            elif msg_type == "audio_start":
                logger.info(f"[{client_id}] Audio stream started")
                self.audio_buffers[client_id] = bytearray()
                self.audio_chunks[client_id] = []
                # 立即建立ASR连接（节省后续延迟）
                asyncio.create_task(self._start_asr_stream(client_id, sender_id))

            # ─── 新增：音频分块 ──────────────────────────────────────────
            elif msg_type == "audio_chunk":
                chunk_b64 = msg.get("data", "")
                seq = msg.get("seq", 0)
                is_last = msg.get("is_last", False)

                if chunk_b64:
                    chunk = base64.b64decode(chunk_b64)
                    # 累计到 buffer（备用完整音频）
                    self.audio_buffers.setdefault(client_id, bytearray()).extend(chunk)
                    # 追加到 chunk 列表（用于最终整体识别）
                    self.audio_chunks.setdefault(client_id, []).append(chunk)

                    # 如果ASR流已建立，立即转发
                    streamer = self.asr_streams.get(client_id)
                    if streamer:
                        await streamer.send_audio_chunk(chunk, is_last=is_last)

                    # 如果是最后一块，开始接收ASR响应
                    if is_last:
                        logger.info(f"[{client_id}] Audio stream ended, {len(self.audio_chunks.get(client_id, []))} chunks")
                        asyncio.create_task(self._finish_asr_stream(client_id, sender_id))

            # ─── 新增：流式音频结束（备用，is_last也能触发上面逻辑）────────
            elif msg_type == "audio_end":
                logger.info(f"[{client_id}] Audio end signal received")

        except Exception as e:
            logger.error(f"Error handling message: {e}")
            await self._send_error(client_id, str(e))

    async def _start_asr_stream(self, client_id: str, sender_id: str) -> None:
        """建立ASR流式连接"""
        try:
            from .huoshan_streamer import AsrStreamer

            streamer = AsrStreamer(
                url=self.asr_url,
                app_key=self.config.asr_app_id,
                access_key=self.config.asr_access_key,
                segment_duration=200,
            )
            self.asr_streams[client_id] = streamer
            await streamer.connect()
            logger.info(f"[{client_id}] ASR stream connected")

        except Exception as e:
            logger.error(f"[{client_id}] Failed to start ASR stream: {e}")
            self.asr_streams.pop(client_id, None)

    async def _finish_asr_stream(self, client_id: str, sender_id: str) -> None:
        """
        结束ASR流式识别：关闭sender，等待剩余的ASR响应返回，
        然后将最终文字送给agent处理。
        """
        streamer = self.asr_streams.pop(client_id, None)
        if not streamer:
            logger.warning(f"[{client_id}] No ASR streamer to finish")
            return

        try:
            chunks = self.audio_chunks.get(client_id, [])
            if not chunks:
                logger.warning(f"[{client_id}] No audio chunks collected")
                await self._send_error(client_id, "No audio data")
                await streamer.close()
                return

            # 收集所有ASR响应（最后一个包含完整文字）
            all_texts = []
            async for response in streamer.recv_until_last():
                if response.payload_msg:
                    result = response.payload_msg.get('result', {})
                    if isinstance(result, dict):
                        text = result.get('text', '')
                    elif isinstance(result, str):
                        text = result
                    else:
                        text = ''

                    if text:
                        all_texts.append(text)
                        # 实时回传 partial 结果
                        await self._send_asr_partial(client_id, text)

            await streamer.close()

            # 取最后一个（最完整的）结果送给agent
            final_text = all_texts[-1] if all_texts else ''
            if final_text:
                await self._send_asr_done(client_id)
                await self._handle_message(sender_id, client_id, final_text)
            else:
                await self._send_error(client_id, "ASR returned no text")

        except Exception as e:
            logger.error(f"[{client_id}] Error finishing ASR stream: {e}")
            await self._send_error(client_id, f"ASR error: {e}")
            try:
                await streamer.close()
            except Exception:
                pass

    async def _process_audio_batch(self, audio_base64: str, sender_id: str, chat_id: str) -> None:
        """
        原有整体音频处理逻辑（向后兼容）。
        用户一次发送整段音频，等ASR全部跑完再处理。
        """
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
                await self._handle_message(sender_id, chat_id, text_result)
            else:
                await self._send_error(chat_id, "ASR failed")

        except Exception as e:
            logger.error(f"Audio processing error: {e}")
            await self._send_error(chat_id, f"Audio error: {e}")

    async def send(self, msg: OutboundMessage) -> None:
        """Send message to Android client. Supports streaming via metadata."""
        ws = self.clients.get(msg.chat_id)
        if not ws or ws.closed:
            logger.warning(f"Client {msg.chat_id} not connected")
            return

        try:
            if msg.metadata and msg.metadata.get("_progress"):
                # Agent思考/工具调用进度
                await ws.send_json({
                    "type": "asr_partial",
                    "content": msg.content,
                })
            else:
                await ws.send_json({
                    "type": "message",
                    "content": msg.content,
                    "status": "done"
                })
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

    async def _send_asr_partial(self, chat_id: str, content: str) -> None:
        """实时回传ASR partial结果给Android"""
        ws = self.clients.get(chat_id)
        if ws and not ws.closed:
            await ws.send_json({
                "type": "asr_partial",
                "content": content,
            })

    async def _send_asr_done(self, chat_id: str) -> None:
        """告知Android ASR识别完成"""
        ws = self.clients.get(chat_id)
        if ws and not ws.closed:
            await ws.send_json({"type": "asr_done"})
