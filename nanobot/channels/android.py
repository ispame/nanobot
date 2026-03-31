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

        # 流式音频状态
        self.audio_buffers: dict[str, bytearray] = {}           # client_id -> 累计音频
        self.audio_chunks: dict[str, list[bytes]] = {}         # client_id -> chunk列表
        self.asr_streams: dict[str, Any] = {}                   # client_id -> AsrStreamer
        self.asr_ready: dict[str, asyncio.Event] = {}            # client_id -> 连接就绪事件
        self.pending_chunks: dict[str, list[bytes]] = {}         # client_id -> ASR就绪前的待发chunks

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

        for streamer in self.asr_streams.values():
            try:
                await streamer.close()
            except Exception:
                pass
        self.asr_streams.clear()
        self.audio_buffers.clear()
        self.audio_chunks.clear()
        self.asr_ready.clear()
        self.pending_chunks.clear()

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
            self._cleanup_client(client_id)
            logger.info(f"Android client disconnected: {client_id}")

        return ws

    def _cleanup_client(self, client_id: str) -> None:
        """清理客户端的所有状态（同步方法，供 finally 和 stop 调用）"""
        self.clients.pop(client_id, None)
        self.audio_buffers.pop(client_id, None)
        self.audio_chunks.pop(client_id, None)
        self.asr_ready.pop(client_id, None)
        self.pending_chunks.pop(client_id, None)
        streamer = self.asr_streams.pop(client_id, None)
        if streamer:
            try:
                import asyncio
                asyncio.get_event_loop().create_task(streamer.close())
            except Exception:
                pass

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

            # ─── 流式音频开始 ───────────────────────────────────────────
            elif msg_type == "audio_start":
                logger.info(f"[{client_id}] Audio stream started")
                self.audio_buffers[client_id] = bytearray()
                self.audio_chunks[client_id] = []
                self.pending_chunks[client_id] = []
                self.asr_ready[client_id] = asyncio.Event()
                await self._start_asr_stream(client_id, sender_id)
                # ASR 就绪后 flush 待发送的 chunks
                pending = self.pending_chunks.pop(client_id, [])
                if pending:
                    logger.info(f"[{client_id}] Flushing {len(pending)} pending chunks")
                    for ch in pending:
                        st = self.asr_streams.get(client_id)
                        if st and not st.conn.closed:
                            await st.send_raw_chunk(ch)

            # ─── 音频分块 ───────────────────────────────────────────────
            elif msg_type == "audio_chunk":
                chunk_b64 = msg.get("data", "")
                is_last = msg.get("is_last", False)

                if chunk_b64:
                    chunk = base64.b64decode(chunk_b64)
                    self.audio_buffers.setdefault(client_id, bytearray()).extend(chunk)
                    self.audio_chunks.setdefault(client_id, []).append(chunk)

                    # ASR 已就绪则立即发送；否则缓存
                    ready = self.asr_ready.get(client_id)
                    if ready and ready.is_set():
                        st = self.asr_streams.get(client_id)
                        if st and not st.conn.closed:
                            await st.send_raw_chunk(chunk)
                        else:
                            self.pending_chunks.setdefault(client_id, []).append(chunk)
                    else:
                        self.pending_chunks.setdefault(client_id, []).append(chunk)

                    if is_last:
                        logger.info(f"[{client_id}] Last chunk, {len(self.audio_chunks.get(client_id, []))} total")
                        asyncio.create_task(self._finish_asr_stream(client_id, sender_id, is_last_chunk=chunk))

            elif msg_type == "audio_end":
                logger.info(f"[{client_id}] Audio end signal received")

        except Exception as e:
            logger.error(f"Error handling message: {e}")
            await self._send_error(client_id, str(e))

    async def _start_asr_stream(self, client_id: str, sender_id: str) -> None:
        """建立ASR流式连接（同步等待连接就绪）"""
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
            self.asr_ready[client_id].set()
            logger.info(f"[{client_id}] ASR stream connected")

        except Exception as e:
            logger.error(f"[{client_id}] Failed to start ASR stream: {e}")
            self.asr_streams.pop(client_id, None)
            self.asr_ready[client_id].set()  # unblock waiting coroutines

    async def _finish_asr_stream(self, client_id: str, sender_id: str, is_last_chunk: bytes | None = None) -> None:
        """
        结束ASR流式识别：
        1. 发送最后一个 is_last chunk
        2. 接收剩余ASR响应
        3. 关闭连接
        4. 把最终文字送给agent
        """
        st = self.asr_streams.get(client_id)
        if not st or st.conn.closed:
            logger.warning(f"[{client_id}] ASR streamer not available")
            return

        # 发送最后一个 is_last chunk（触发 ASR 返回最终结果）
        if is_last_chunk:
            try:
                await st.send_audio_chunk(is_last_chunk, is_last=True)
            except Exception as e:
                logger.error(f"[{client_id}] Failed to send is_last chunk: {e}")
                await self._send_error(client_id, f"ASR send error: {e}")
                try:
                    await st.close()
                except Exception:
                    pass
                self.asr_streams.pop(client_id, None)
                return

        # 清理状态
        self.asr_ready.pop(client_id, None)
        self.pending_chunks.pop(client_id, None)

        # 发送 is_last 结束标记（由 recv_until_last 触发）
        try:
            all_texts = []
            async for response in st.recv_until_last():
                if response.payload_msg:
                    result = response.payload_msg.get('result', {})
                    text = result.get('text', '') if isinstance(result, dict) else (result if isinstance(result, str) else '')
                    if text:
                        all_texts.append(text)
                        await self._send_asr_partial(client_id, text)

            await st.close()
            self.asr_streams.pop(client_id, None)

            final_text = all_texts[-1] if all_texts else ''
            if final_text:
                await self._send_asr_done(client_id)
                await self._handle_message(sender_id, client_id, final_text)
            else:
                await self._send_error(client_id, "ASR returned no text")

        except asyncio.CancelledError:
            logger.info(f"[{client_id}] ASR stream cancelled")
            try:
                await st.close()
            except Exception:
                pass
            self.asr_streams.pop(client_id, None)
            raise
        except Exception as e:
            logger.error(f"[{client_id}] Error finishing ASR stream: {e}")
            await self._send_error(client_id, f"ASR error: {e}")
            try:
                await st.close()
            except Exception:
                pass
            self.asr_streams.pop(client_id, None)

    async def _process_audio_batch(self, audio_base64: str, sender_id: str, chat_id: str) -> None:
        """原有整体音频处理逻辑（向后兼容）"""
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
                await ws.send_json({"type": "asr_partial", "content": msg.content})
            else:
                await ws.send_json({
                    "type": "message",
                    "content": msg.content,
                    "status": "done"
                })
        except Exception as e:
            logger.error(f"Send error: {e}")

    async def _send_status(self, chat_id: str, status: str) -> None:
        ws = self.clients.get(chat_id)
        if ws and not ws.closed:
            await ws.send_json({"type": "status", "status": status})

    async def _send_error(self, chat_id: str, error: str) -> None:
        ws = self.clients.get(chat_id)
        if ws and not ws.closed:
            await ws.send_json({"type": "status", "status": "error", "message": error})

    async def _send_asr_partial(self, chat_id: str, content: str) -> None:
        ws = self.clients.get(chat_id)
        if ws and not ws.closed:
            await ws.send_json({"type": "asr_partial", "content": content})

    async def _send_asr_done(self, chat_id: str) -> None:
        ws = self.clients.get(chat_id)
        if ws and not ws.closed:
            await ws.send_json({"type": "asr_done"})
