"""MiOT (Mi Home IoT) service for Xiaomi devices.

This module provides a Python implementation of the MiHome API for controlling
Xiaomi devices like Xiao AI speakers. It handles authentication, device management,
and device control (TTS, status, etc.).

Based on the migpt-next TypeScript implementation.
"""

import base64
import gzip
import hashlib
import json
import random
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from loguru import logger


def sign_nonce(ssecurity: str, nonce: str) -> str:
    """Sign nonce with ssecurity."""
    ssecurity_bytes = base64.b64decode(ssecurity)
    # If nonce is numeric string, encode it differently
    try:
        nonce_bytes = str(nonce).encode('utf-8')
    except:
        nonce_bytes = nonce
    h = hashlib.sha256()
    h.update(ssecurity_bytes)
    h.update(nonce_bytes)
    return base64.b64encode(h.digest()).decode()


def random_noise() -> str:
    """Generate random noise (12 bytes base64 encoded)."""
    return base64.b64encode(bytes(random.randint(0, 255) for _ in range(12))).decode()


def rc4_encrypt(key: bytes, data: bytes) -> bytes:
    """RC4 encrypt data with key."""
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) % 256
        S[i], S[j] = S[j], S[i]
    i = j = 0
    result = bytearray(len(data))
    for k in range(len(data)):
        i = (i + 1) % 256
        j = (j + S[i]) % 256
        S[i], S[j] = S[j], S[i]
        result[k] = data[k] ^ S[(S[i] + S[j]) % 256]
    return bytes(result)


def sha1_base64(data: str) -> bytes:
    """Calculate SHA1 hash."""
    return hashlib.sha1(data.encode()).digest()


def rc4_hash(method: str, uri: str, data: dict, ssecurity: str) -> str:
    """Calculate RC4 hash for MIoT request signature."""
    array_list = [method.upper(), uri]
    for k, v in data.items():
        array_list.append(f"{k}={v}")
    array_list.append(ssecurity)
    sb = "&".join(array_list)
    return base64.b64encode(sha1_base64(sb)).decode()


def encode_miot(method: str, uri: str, data: Any, ssecurity: str) -> dict:
    """Encode MIoT request data."""
    nonce = random_noise()
    snonce = sign_nonce(ssecurity, nonce)
    key = base64.b64decode(snonce)
    rc4_encrypt(key, bytes(1024))
    json_data = json.dumps(data, separators=(",", ":"))
    map_data = {"data": json_data}
    map_data["rc4_hash__"] = rc4_hash(method, uri, {"data": json_data}, snonce)
    for k, v in map_data.items():
        if isinstance(v, str):
            map_data[k] = base64.b64encode(rc4_encrypt(key, v.encode())).decode()
    map_data["signature"] = rc4_hash(method, uri, map_data, snonce)
    map_data["_nonce"] = nonce
    map_data["ssecurity"] = ssecurity
    return map_data


class MiOTService:
    """MiOT service for Xiaomi device control."""

    API_BASE = "https://api.io.mi.com/app"
    MINA_API = "https://api2.mina.mi.com"

    # Device IDs for Xiao AI speakers
    DEVICE_IDS = {
        "speaker": "7",
        "speaker_pro": "5",
        "speaker_screen": "6",
        "speaker_art": "0",
    }

    def __init__(
        self,
        user_id: str | None = None,
        pass_token: str | None = None,
        device_name: str | None = None,
        config_path: str | None = None,
        timeout: float = 30.0,
    ):
        """Initialize MiOT service.

        Args:
            user_id: Xiaomi user ID (optional if using config_path)
            pass_token: Xiaomi passToken or password (optional if using config_path)
            device_name: Device name (optional if using config_path)
            config_path: Path to .mi.json file (from migpt-next)
            timeout: HTTP request timeout in seconds
        """
        self.user_id = user_id
        self.pass_token = pass_token
        self.device_name = device_name
        self.timeout = timeout

        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "User-Agent": "MICO/AndroidApp/@SHIP.TO.2A2FE0D7@/2.4.40",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

        self._service_token: str | None = None
        self._ssecurity: str | None = None
        self._c_user_id: str | None = None
        self._device_id_str: str | None = None
        self._device_info: dict[str, Any] | None = None
        self._did: str | None = None

        # Load from config file if provided
        if config_path:
            self._load_from_config(config_path)

    def _load_from_config(self, config_path: str) -> bool:
        """Load authentication from .mi.json config file."""
        try:
            path = Path(config_path)
            if not path.exists():
                logger.error("Config file not found: {}", config_path)
                return False

            with open(path) as f:
                data = json.load(f)

            # Try to load from 'mina' or 'miot' key
            account = data.get("mina") or data.get("miot")
            if not account:
                logger.error("No 'mina' or 'miot' key in config file")
                return False

            # Extract authentication info
            self._service_token = account.get("serviceToken")
            self.user_id = account.get("userId")
            self._device_id_str = account.get("deviceId")
            self._did = account.get("did")

            # Get pass info
            pass_info = account.get("pass", {})
            self._ssecurity = pass_info.get("ssecurity")
            self._c_user_id = pass_info.get("cUserId")

            # Get device info
            device = account.get("device", {})
            if device:
                self._device_info = {
                    "did": device.get("miotDID") or account.get("did"),
                    "name": device.get("name"),
                    "alias": device.get("alias"),
                    "deviceId": device.get("deviceId"),
                    "deviceID": device.get("deviceID"),
                    "serialNumber": device.get("serialNumber"),
                    "hardware": device.get("hardware"),
                    "deviceSNProfile": device.get("deviceSNProfile"),
                }

            logger.info("Loaded config from: {}", config_path)
            logger.info("  userId: {}", self.user_id)
            logger.info("  did: {}", self._did)
            logger.info("  device: {}", self._device_info.get("name") if self._device_info else "None")

            return True

        except Exception as e:
            logger.error("Failed to load config: {}", e)
            return False

    async def login(self) -> bool:
        """Login to Xiaomi account."""
        if self._service_token and self._ssecurity:
            logger.info("Using existing authentication from config")
            return True

        if self.user_id and self.pass_token:
            logger.error("Password login not implemented. Use migpt-next to get .mi.json config")
            return False

        logger.error("No authentication available")
        return False

    def _build_mina_cookies(self) -> str:
        """Build cookies for MiNA API."""
        cookies = {
            "userId": self.user_id or "",
            "serviceToken": self._service_token or "",
        }
        if self._device_info:
            cookies["sn"] = self._device_info.get("serialNumber", "")
            cookies["hardware"] = self._device_info.get("hardware", "")
            cookies["deviceId"] = self._device_info.get("deviceId", "")
            cookies["deviceSNProfile"] = self._device_info.get("deviceSNProfile", "")
        return "; ".join(f"{k}={v}" for k, v in cookies.items())

    def _build_miot_cookies(self) -> str:
        """Build cookies for MIoT API."""
        cookies = {
            "countryCode": "CN",
            "locale": "zh_CN",
            "timezone": "GMT+08:00",
            "timezone_id": "Asia/Shanghai",
            "userId": self.user_id or "",
            "cUserId": self._c_user_id or "",
            "PassportDeviceId": self._device_id_str or "",
            "serviceToken": self._service_token or "",
            "yetAnotherServiceToken": self._service_token or "",
        }
        return "; ".join(f"{k}={v}" for k, v in cookies.items())

    async def get_device_list(self) -> list[dict[str, Any]] | None:
        """Get list of devices for the account."""
        if not self._service_token or not self._ssecurity:
            if not await self.login():
                return None

        try:
            url = f"{self.API_BASE}/home/device_list"
            payload = {"getVirtualModel": False, "getHuamiDevices": 0}
            signed_payload = encode_miot("POST", "/home/device_list", payload, self._ssecurity)

            headers = {
                "User-Agent": "MICO/AndroidApp/@SHIP.TO.2A2FE0D7@/2.4.40",
                "x-xiaomi-protocal-flag-cli": "PROTOCAL-HTTP2",
                "miot-accept-encoding": "GZIP",
                "miot-encrypt-algorithm": "ENCRYPT-RC4",
                "Cookie": self._build_miot_cookies(),
            }

            response = await self._client.post(url, data=signed_payload, headers=headers)
            logger.debug("Device list response: {} - {}", response.status_code, response.text[:200])

            return []

        except Exception as e:
            logger.error("MiOT get device list error: {}", e)
            return None

    async def find_device(self) -> dict[str, Any] | None:
        """Find device by name or use configured device."""
        if self._device_info:
            return self._device_info
        return None

    async def play_tts(self, text: str) -> bool:
        """Play TTS on the device using MiNA API."""
        if not self._service_token:
            if not await self.login():
                return False

        if not self._device_info:
            logger.error("No device configured")
            return False

        try:
            # Try MiNA play method first (preferred)
            url = f"{self.MINA_API}/v2/mipush"

            payload = {
                "deviceId": self._device_info.get("deviceId"),
                "method": "play",
                "params": json.dumps({"tts": text}),
            }

            headers = {
                "User-Agent": "MICO/AndroidApp/@SHIP.TO.2A2FE0D7@/2.4.40",
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": self._build_mina_cookies(),
            }

            response = await self._client.post(url, data=payload, headers=headers)

            if response.status_code == 200:
                result = response.json()
                logger.info("TTS sent via MiNA: {}", result)
                # Consider success if HTTP 200 (code 0 or 101 may both work)
                return result.get("code") in [0, 101]

            logger.warning("MiNA play failed, trying mibrain text_to_speech: {} - {}", response.status_code, response.text)

            # Fallback to mibrain text_to_speech (like migpt-next)
            url2 = f"{self.MINA_API}/remote/ubus"
            payload2 = {
                "deviceId": self._device_info.get("deviceId"),
                "path": "mibrain",
                "method": "text_to_speech",
                "message": json.dumps({"text": text, "save": 0}),
                "requestId": str(uuid.uuid4()),
                "timestamp": int(time.time()),
            }

            response2 = await self._client.post(url2, data=payload2, headers=headers)

            if response2.status_code == 200:
                result2 = response2.json()
                logger.info("TTS sent via tts_play: {}", result2)
                # Code 101 with device_data.code 900 means device received the request
                # Consider success if HTTP 200 (the TTS actually plays)
                return True

            logger.error("TTS failed: {} - {}", response2.status_code, response2.text)
            return False

        except Exception as e:
            logger.error("MiOT TTS error: {}", e)
            return False

    async def do_action(
        self,
        siid: int,
        aiid: int,
        args: list | dict | None = None,
    ) -> bool:
        """Execute action on the device using MIoT API."""
        if not self._device_info:
            await self.find_device()

        if not self._device_info:
            return False

        try:
            url = f"{self.API_BASE}/miotspec/action"
            did = self._device_info.get("did") or self._did

            # Format matches mi-service-lite: params + datasource
            payload = {
                "params": json.dumps({
                    "did": did,
                    "siid": siid,
                    "aiid": aiid,
                    "in": args if isinstance(args, list) else [args] if args else [],
                }),
                "datasource": 2,
            }

            signed_payload = encode_miot("POST", "/miotspec/action", payload, self._ssecurity)

            headers = {
                "User-Agent": "MICO/AndroidApp/@SHIP.TO.2A2FE0D7@/2.4.40",
                "x-xiaomi-protocal-flag-cli": "PROTOCAL-HTTP2",
                "miot-accept-encoding": "GZIP",
                "miot-encrypt-algorithm": "ENCRYPT-RC4",
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": self._build_miot_cookies(),
            }

            response = await self._client.post(url, data=signed_payload, headers=headers)

            if response.status_code == 200:
                return True
            else:
                logger.error("MIoT action failed: {} - {}", response.status_code, response.text)
                return False

        except Exception as e:
            logger.error("MiOT action error: {}", e)
            return False

    async def get_voice_memos(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get voice memos/recordings from the device.

        Args:
            limit: Maximum number of memos to retrieve.

        Returns:
            List of voice memo dicts with 'id', 'text', 'audio_url', 'timestamp'.
        """
        if not self._service_token:
            if not await self.login():
                return []

        if not self._device_info:
            await self.find_device()

        if not self._device_info:
            logger.error("No device configured for voice memos")
            return []

        try:
            # Use MiNA API to get voice memos
            # This endpoint provides recent voice interactions
            url = f"{self.MINA_API}/v2/voice/memos"

            payload = {
                "deviceId": self._device_info.get("deviceId"),
                "limit": limit,
            }

            headers = {
                "User-Agent": "MICO/AndroidApp/@SHIP.TO.2A2FE0D7@/2.4.40",
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": self._build_mina_cookies(),
            }

            response = await self._client.post(url, data=payload, headers=headers)

            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0:
                    memos = result.get("data", {}).get("memos", [])
                    logger.debug("Got {} voice memos", len(memos))
                    return memos
                else:
                    logger.warning("Voice memos API returned code: {}", result.get("code"))

            logger.debug("Voice memos request: {} - {}", response.status_code, response.text[:200])
            return []

        except Exception as e:
            logger.error("MiOT get voice memos error: {}", e)
            return []

    async def get_conversation_history(self, limit: int = 10, timestamp: int | None = None) -> list[dict[str, Any]]:
        """Get conversation history from the device.

        Args:
            limit: Maximum number of conversations to retrieve.
            timestamp: Optional timestamp to get conversations before this time.

        Returns:
            List of conversation dicts with 'id', 'query', 'answer', 'timestamp', 'time'.
        """
        if not self._service_token:
            if not await self.login():
                return []

        if not self._device_info:
            await self.find_device()

        if not self._device_info:
            logger.error("No device configured for conversation history")
            return []

        try:
            # Use userprofile.mina.mi.com API to get conversation history
            # Based on migpt-next implementation
            url = "https://userprofile.mina.mi.com/device_profile/v2/conversation"

            params = {
                "limit": limit,
                "timestamp": timestamp or int(time.time() * 1000),
                "requestId": str(uuid.uuid4()),
                "source": "dialogu",
                "hardware": self._device_info.get("hardware", ""),
            }

            headers = {
                "User-Agent": "Mozilla/5.0 (Linux; Android 10; 000; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/119.0.6045.193 Mobile Safari/537.36 /XiaoMi/HybridView/ micoSoundboxApp/i appVersion/A_2_4.40",
                "Referer": "https://userprofile.mina.mi.com/dialogue-note/index.html",
            }

            cookies = {
                "userId": self.user_id or "",
                "serviceToken": self._service_token or "",
                "deviceId": self._device_info.get("deviceId", ""),
            }

            response = await self._client.get(
                url,
                params=params,
                headers=headers,
                cookies=cookies,
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0:
                    data = result.get("data")
                    # Data is a JSON string, need to parse it
                    if isinstance(data, str):
                        import json as json_mod
                        data = json_mod.loads(data)

                    records = data.get("records", []) if isinstance(data, dict) else []

                    # Transform to simpler format
                    conversations = []
                    for record in records:
                        query_data = record.get("query", {})
                        query_text = query_data.get("text", "") if isinstance(query_data, dict) else str(query_data)

                        # Get answer text
                        answers = record.get("answers", [])
                        answer_text = ""
                        if answers:
                            first_answer = answers[0]
                            if first_answer.get("type") == "TTS":
                                answer_text = first_answer.get("tts", {}).get("text", "") or ""
                            elif first_answer.get("type") == "LLM":
                                answer_text = first_answer.get("llm", {}).get("text", "") or ""

                        conversations.append({
                            "id": str(record.get("time", "")),
                            "query": query_text,
                            "answer": answer_text,
                            "timestamp": record.get("time"),
                            "time": record.get("time"),
                        })
                    return conversations
                else:
                    logger.warning("Conversation history API returned code: {}", result.get("code"))

            return []

        except Exception as e:
            logger.error("MiOT get conversation history error: {}", e)
            return []

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    @property
    def is_logged_in(self) -> bool:
        """Check if logged in."""
        return self._service_token is not None and self._ssecurity is not None

    @property
    def device_info(self) -> dict[str, Any] | None:
        """Get current device info."""
        return self._device_info
