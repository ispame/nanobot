"""火山ASR流式客户端 - 支持边收音频chunk边返回partial结果"""

import asyncio
import aiohttp
import json
import struct
import gzip
import uuid
import logging
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

DEFAULT_SAMPLE_RATE = 16000


class ProtocolVersion:
    V1 = 0b0001


class MessageType:
    CLIENT_FULL_REQUEST = 0b0001
    CLIENT_AUDIO_ONLY_REQUEST = 0b0010
    SERVER_FULL_RESPONSE = 0b1001
    SERVER_ERROR_RESPONSE = 0b1111


class MessageTypeSpecificFlags:
    NO_SEQUENCE = 0b0000
    POS_SEQUENCE = 0b0001
    NEG_SEQUENCE = 0b0010
    NEG_WITH_SEQUENCE = 0b0011


class SerializationType:
    NO_SERIALIZATION = 0b0000
    JSON = 0b0001


class CompressionType:
    GZIP = 0b0001


class AsrResponse:
    def __init__(self):
        self.code = 0
        self.event = 0
        self.is_last_package = False
        self.payload_sequence = 0
        self.payload_size = 0
        self.payload_msg = None

    def __repr__(self):
        text = ""
        if self.payload_msg:
            result = self.payload_msg.get('result', {})
            if isinstance(result, dict):
                text = result.get('text', '')
            elif isinstance(result, str):
                text = result
        return f"AsrResponse(code={self.code}, is_last={self.is_last_package}, text={text!r})"


def gzip_compress(data: bytes) -> bytes:
    return gzip.compress(data)


def gzip_decompress(data: bytes) -> bytes:
    return gzip.decompress(data)


def build_header(
    message_type: int = MessageType.CLIENT_AUDIO_ONLY_REQUEST,
    flags: int = MessageTypeSpecificFlags.POS_SEQUENCE,
    serialization: int = SerializationType.JSON,
    compression: int = CompressionType.GZIP,
) -> bytes:
    """构建4字节ASR请求头"""
    header = bytearray()
    header.append((ProtocolVersion.V1 << 4) | 1)
    header.append((message_type << 4) | flags)
    header.append((serialization << 4) | compression)
    header.extend(bytes([0x00]))
    return bytes(header)


def build_full_request(seq: int) -> bytes:
    """构建CLIENT_FULL_REQUEST"""
    payload = {
        "user": {"uid": "demo_uid"},
        "audio": {
            "format": "wav",
            "codec": "raw",
            "rate": 16000,
            "bits": 16,
            "channel": 1
        },
        "request": {
            "model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": True,
            "enable_ddc": True,
            "show_utterances": True,
            "enable_nonstream": False
        }
    }
    payload_bytes = json.dumps(payload).encode('utf-8')
    compressed = gzip_compress(payload_bytes)

    req = bytearray()
    req.extend(build_header(
        message_type=MessageType.CLIENT_FULL_REQUEST,
        flags=MessageTypeSpecificFlags.POS_SEQUENCE,
    ))
    req.extend(struct.pack('>i', seq))
    req.extend(struct.pack('>I', len(compressed)))
    req.extend(compressed)
    return bytes(req)


def build_audio_request(seq: int, chunk: bytes, is_last: bool = False) -> bytes:
    """构建CLIENT_AUDIO_ONLY_REQUEST"""
    if is_last:
        flags = MessageTypeSpecificFlags.NEG_WITH_SEQUENCE
        seq = -seq
    else:
        flags = MessageTypeSpecificFlags.POS_SEQUENCE

    compressed = gzip_compress(chunk)
    req = bytearray()
    req.extend(build_header(
        message_type=MessageType.CLIENT_AUDIO_ONLY_REQUEST,
        flags=flags,
    ))
    req.extend(struct.pack('>i', seq))
    req.extend(struct.pack('>I', len(compressed)))
    req.extend(compressed)
    return bytes(req)


def parse_response(msg: bytes) -> AsrResponse:
    """解析ASR服务器响应"""
    response = AsrResponse()

    header_size = msg[0] & 0x0f
    message_type = msg[1] >> 4
    flags = msg[1] & 0x0f
    serialization = msg[2] >> 4
    compression = msg[2] & 0x0f

    payload = msg[header_size * 4:]

    if flags & 0x01:
        response.payload_sequence = struct.unpack('>i', payload[:4])[0]
        payload = payload[4:]
    if flags & 0x02:
        response.is_last_package = True
    if flags & 0x04:
        response.event = struct.unpack('>i', payload[:4])[0]
        payload = payload[4:]

    if message_type == MessageType.SERVER_FULL_RESPONSE:
        response.payload_size = struct.unpack('>I', payload[:4])[0]
        payload = payload[4:]
    elif message_type == MessageType.SERVER_ERROR_RESPONSE:
        response.code = struct.unpack('>i', payload[:4])[0]
        response.payload_size = struct.unpack('>I', payload[4:8])[0]
        payload = payload[8:]

    if not payload:
        return response

    if compression == CompressionType.GZIP:
        try:
            payload = gzip_decompress(payload)
        except Exception:
            return response

    if serialization == SerializationType.JSON:
        try:
            response.payload_msg = json.loads(payload.decode('utf-8'))
        except Exception:
            pass

    return response


class AsrStreamer:
    """流式ASR客户端 - 支持边发送音频边接收partial结果"""

    def __init__(
        self,
        url: str,
        app_key: str,
        access_key: str,
        segment_duration: int = 200,
    ):
        self.url = url
        self.app_key = app_key
        self.access_key = access_key
        self.segment_duration = segment_duration  # ms
        self.seq = 1
        self.conn: aiohttp.ClientWebSocketResponse | None = None
        self.session: aiohttp.ClientSession | None = None
        self._active = True  # False when connection is confirmed dead

    def _auth_headers(self) -> dict:
        reqid = str(uuid.uuid4())
        return {
            "X-Api-Resource-Id": "volc.bigasr.sauc.duration",
            "X-Api-Request-Id": reqid,
            "X-Api-Access-Key": self.access_key,
            "X-Api-App-Key": self.app_key,
        }

    async def connect(self) -> None:
        """建立WS连接"""
        import sys
        self.session = aiohttp.ClientSession()
        headers = self._auth_headers()
        logger.info(f"[AsrStreamer] Connecting to {self.url}")
        logger.info(f"[AsrStreamer] Auth headers: app_key={self.app_key[:8]}..., access_key={self.access_key[:8]}...")
        try:
            self.conn = await self.session.ws_connect(
                self.url,
                headers=headers,
            )
            logger.info(f"[AsrStreamer] ✅ WS connected to {self.url}")
        except Exception as e:
            logger.error(f"[AsrStreamer] ❌ WS connection failed: {e}")
            raise

    async def _send_full_request(self) -> None:
        """发送初始full request"""
        req = build_full_request(self.seq)
        self.seq += 1
        logger.info(f"[AsrStreamer] Sending full request (seq={self.seq-1}), request size={len(req)} bytes")
        await self.conn.send_bytes(req)
        logger.info("[AsrStreamer] Full request sent, waiting for server response...")

        # 等待并打印服务器对 full request 的响应
        try:
            msg = await asyncio.wait_for(self.conn.receive(), timeout=5.0)
            if msg.type == aiohttp.WSMsgType.BINARY:
                resp = parse_response(msg.data)
                logger.info(f"[AsrStreamer] Full request response: code={resp.code}, is_last={resp.is_last_package}, payload={resp.payload_msg}")
            elif msg.type == aiohttp.WSMsgType.TEXT:
                logger.warning(f"[AsrStreamer] Full request response (text): {msg.data}")
            elif msg.type == aiohttp.WSMsgType.ERROR:
                logger.error(f"[AsrStreamer] Full request error response: {msg.data}")
            else:
                logger.warning(f"[AsrStreamer] Full request unexpected msg type: {msg.type}")
        except asyncio.TimeoutError:
            logger.warning("[AsrStreamer] Full request: timeout waiting for server response")
        except Exception as e:
            logger.error(f"[AsrStreamer] Full request response error: {e}")

    async def send_audio_chunk(self, chunk: bytes, is_last: bool = False) -> None:
        """发送一个音频chunk（带200ms延迟，用于整体发送场景）"""
        if not self.conn or self.conn.closed:
            logger.warning("[AsrStreamer] Cannot send, connection not ready or closed")
            return
        req = build_audio_request(self.seq, chunk, is_last=is_last)
        if not is_last:
            self.seq += 1
        await self.conn.send_bytes(req)
        await asyncio.sleep(self.segment_duration / 1000.0)

    async def send_raw_chunk(self, chunk: bytes) -> None:
        """发送一个音频chunk（无sleep，用于流式转发，不阻塞消息处理）"""
        if not self.conn or self.conn.closed or not self._active:
            logger.warning(f"[AsrStreamer] send_raw_chunk: skipped, conn={self.conn is not None}, closed={getattr(self.conn, 'closed', 'N/A')}, active={self._active}")
            return
        req = build_audio_request(self.seq, chunk, is_last=False)
        self.seq += 1
        try:
            await self.conn.send_bytes(req)
            logger.debug(f"[AsrStreamer] ✅ Sent chunk seq={self.seq-1}, size={len(chunk)}")
        except Exception as e:
            logger.error(f"[AsrStreamer] ❌ send_raw_chunk error: {e}")
            self._active = False

    async def send_last_chunk(self, chunk: bytes) -> None:
        """发送最后一个 is_last=True chunk，触发 ASR 返回最终结果（不带sleep）"""
        if not self.conn or self.conn.closed or not self._active:
            logger.warning("[AsrStreamer] Cannot send last chunk, connection not ready")
            self._active = False
            return
        req = build_audio_request(self.seq, chunk, is_last=True)
        try:
            await self.conn.send_bytes(req)
        except Exception as e:
            logger.error(f"[AsrStreamer] send_last_chunk error: {e}")
            self._active = False

    async def recv_one(self) -> AsrResponse | None:
        """接收一条ASR响应"""
        try:
            msg = await self.conn.receive()
            if msg.type == aiohttp.WSMsgType.BINARY:
                return parse_response(msg.data)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                logger.error(f"[AsrStreamer] WS error: {msg.data}")
            elif msg.type == aiohttp.WSMsgType.CLOSED:
                logger.info("[AsrStreamer] WS closed")
        except Exception as e:
            logger.error(f"[AsrStreamer] recv error: {e}")
        return None

    async def recv_until_last(self) -> AsyncGenerator[AsrResponse, None]:
        """仅接收响应直到最后一个包（不在此方法中发送任何数据）"""
        try:
            logger.info("[AsrStreamer] recv_until_last: starting receive loop")
            count = 0
            async for msg in self.conn:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    response = parse_response(msg.data)
                    count += 1
                    text = ''
                    if response.payload_msg:
                        result = response.payload_msg.get('result', {})
                        text = result.get('text', '') if isinstance(result, dict) else (result if isinstance(result, str) else '')
                    logger.info(f"[AsrStreamer] recv [{count}]: code={response.code}, is_last={response.is_last_package}, text={text!r}")
                    yield response
                    if response.is_last_package or response.code != 0:
                        logger.info(f"[AsrStreamer] recv_until_last: terminating (is_last={response.is_last_package}, code={response.code})")
                        break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"[AsrStreamer] WS error: {msg.data}")
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.warning("[AsrStreamer] WS closed by server")
                    break
                elif msg.type == aiohttp.WSMsgType.TEXT:
                    logger.warning(f"[AsrStreamer] Unexpected text message: {msg.data}")
        except asyncio.CancelledError:
            logger.info("[AsrStreamer] recv_until_last cancelled")
            raise
        except Exception as e:
            logger.error(f"[AsrStreamer] recv_until_last error: {e}")

    async def send_chunks_and_wait(self, audio_chunks: list[bytes]) -> None:
        """
        顺序发送所有音频chunks，等待发送完毕。
        不做接收（接收由 recv_until_last 或 stream_audio 负责）。
        发送完毕后正常返回（不是取消）。
        """
        for i, chunk in enumerate(audio_chunks):
            is_last = (i == len(audio_chunks) - 1)
            await self.send_audio_chunk(chunk, is_last=is_last)
            if not is_last:
                await asyncio.sleep(self.segment_duration / 1000.0)

    async def close(self) -> None:
        """关闭连接"""
        self._active = False
        if self.conn and not self.conn.closed:
            await self.conn.close()
        if self.session and not self.session.closed:
            await self.session.close()
        self.conn = None
        self.session = None
        logger.info("[AsrStreamer] Connection closed")
