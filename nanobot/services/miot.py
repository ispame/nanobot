"""MiOT (Mi Home IoT) service for Xiaomi devices.

This module provides a Python implementation of the MiHome API for controlling
Xiaomi devices like Xiao AI speakers. It handles authentication, device management,
and device control (TTS, status, etc.).

Based on the migpt-next TypeScript implementation.
"""

import hashlib
import hmac
import json
import random
import time
from base64 import b64decode, b64encode
from typing import Any

import httpx

from loguru import logger


def md5(data: str) -> str:
    """Calculate MD5 hash."""
    return hashlib.md5(data.encode()).hexdigest()


def sha1(data: str) -> str:
    """Calculate SHA1 hash."""
    return hashlib.sha1(data.encode()).hexdigest()


def rc4_decrypt(key: str, data: str) -> str:
    """RC4 decrypt data with key (pure Python implementation)."""
    key_bytes = key.encode() if isinstance(key, str) else key
    data_bytes = b64decode(data) if isinstance(data, str) else data

    return _rc4_crypt(key_bytes, data_bytes).decode('utf-8')


def rc4_encrypt(key: str, data: str) -> str:
    """RC4 encrypt data with key (pure Python implementation)."""
    key_bytes = key.encode() if isinstance(key, str) else key
    data_bytes = data.encode() if isinstance(data, str) else data

    encrypted = _rc4_crypt(key_bytes, data_bytes)
    return b64encode(encrypted).decode('utf-8')


def _rc4_crypt(key: bytes, data: bytes) -> bytes:
    """RC4 cipher implementation."""
    # Initialize RC4 state
    S = list(range(256))
    j = 0

    # Key scheduling algorithm (KSA)
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) % 256
        S[i], S[j] = S[j], S[i]

    # Pseudo-random generation algorithm (PRGA)
    i = j = 0
    result = bytearray(len(data))

    for k in range(len(data)):
        i = (i + 1) % 256
        j = (j + S[i]) % 256
        S[i], S[j] = S[j], S[i]
        result[k] = data[k] ^ S[(S[i] + S[j]) % 256]

    return bytes(result)


class MiOTService:
    """MiOT service for Xiaomi device control."""

    API_BASE = "https://api.iot.mi.com"
    GATEWAY_BASE = "https://gateway.iot.mi.com"

    # Device IDs for Xiao AI speakers
    DEVICE_IDS = {
        "speaker": "7",  # Xiao AI speaker
        "speaker_pro": "5",  # Xiao AI speaker Pro
        "speaker_screen": "6",  # Xiao AI speaker with screen
        "speaker_art": "0",  # Xiao AI speaker Art
    }

    def __init__(
        self,
        user_id: str,
        pass_token: str,
        device_name: str,
        timeout: float = 30.0,
    ):
        """Initialize MiOT service.

        Args:
            user_id: Xiaomi user ID
            pass_token: Xiaomi account password or passToken
            device_name: Device name as shown in Mi Home app
            timeout: HTTP request timeout in seconds
        """
        self.user_id = user_id
        self.pass_token = pass_token
        self.device_name = device_name
        self.timeout = timeout

        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "User-Agent": "MiHome/6.0.210 (android;6.0.1)  appVersion:6.0.210",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

        self._service_token: str | None = None
        self._pass_token: str | None = None
        self._device_id: str | None = None
        self._device_info: dict[str, Any] | None = None

    async def login(self) -> bool:
        """Login to Xiaomi account and get service token.

        Returns:
            True if login successful, False otherwise
        """
        try:
            # Step 1: Get session and nonce
            login_url = f"{self.API_BASE}/v2/user/login"
            nonce = self._generate_nonce()

            # If pass_token is already a token (not password), use it directly
            if len(self.pass_token) > 32:
                self._pass_token = self.pass_token
                # Try to get service token directly
                return await self._refresh_service_token()

            # Otherwise, treat as password and do full login
            password_hash = md5(self.pass_token)
            signed_nonce = sha1(nonce + password_hash)

            # Encrypt credentials
            encrypted = rc4_encrypt(
                signed_nonce,
                json.dumps({"username": self.user_id, "password": password_hash})
            )

            payload = {
                "encrypted": encrypted,
                "nonce": nonce,
                "signature": sha1(nonce + password_hash + "-----"),
            }

            response = await self._client.post(login_url, data=payload)
            result = response.json()

            if result.get("code") != 0:
                logger.error("MiOT login failed: {}", result.get("message"))
                return False

            data = result.get("data", {})
            self._pass_token = data.get("passToken")
            self._service_token = data.get("serviceToken")
            self._device_id = str(data.get("userId", ""))

            logger.info("MiOT login successful for user: {}", self._device_id)
            return True

        except Exception as e:
            logger.error("MiOT login error: {}", e)
            return False

    async def _refresh_service_token(self) -> bool:
        """Refresh service token.

        Returns:
            True if refresh successful
        """
        if not self._pass_token:
            return False

        try:
            url = f"{self.API_BASE}/v2/user/refreshServiceToken"
            nonce = self._generate_nonce()

            payload = {
                "serviceToken": self._service_token or "",
                "passToken": self._pass_token,
                "nonce": nonce,
            }

            response = await self._client.post(url, data=payload)
            result = response.json()

            if result.get("code") == 0:
                self._service_token = result.get("data", {}).get("serviceToken")
                return True

            # Token invalid, need full login
            return False

        except Exception as e:
            logger.error("MiOT token refresh error: {}", e)
            return False

    async def get_device_list(self) -> list[dict[str, Any]]:
        """Get list of devices for the account.

        Returns:
            List of device information dictionaries
        """
        if not self._service_token:
            logger.error("MiOT not logged in")
            return []

        try:
            url = f"{self.API_BASE}/v2/device/list"
            nonce = self._generate_nonce()

            payload = {
                "pageSize": 200,
                "nonce": nonce,
            }

            signed_payload = self._sign_payload(payload, url)

            response = await self._client.post(
                url,
                data=signed_payload,
                headers={"Authorization": f"Bearer {self._service_token}"},
            )
            result = response.json()

            if result.get("code") != 0:
                logger.error("MiOT get device list failed: {}", result.get("message"))
                return []

            return result.get("data", {}).get("list", [])

        except Exception as e:
            logger.error("MiOT get device list error: {}", e)
            return []

    async def find_device(self) -> dict[str, Any] | None:
        """Find device by name.

        Returns:
            Device info dictionary or None if not found
        """
        devices = await self.get_device_list()

        # Try to find by name or alias
        for device in devices:
            if device.get("name") == self.device_name:
                self._device_info = device
                return device
            if device.get("aliasName") == self.device_name:
                self._device_info = device
                return device

        # Try to find by device type (Xiao AI speaker)
        for device in devices:
            if device.get("deviceType") in [
                self.DEVICE_IDS["speaker"],
                self.DEVICE_IDS["speaker_pro"],
                self.DEVICE_IDS["speaker_screen"],
                self.DEVICE_IDS["speaker_art"],
            ]:
                if device.get("name", "").lower().replace(" ", "").find(
                    self.device_name.lower().replace(" ", "")
                ) >= 0:
                    self._device_info = device
                    return device

        logger.error("MiOT device not found: {}", self.device_name)
        return None

    async def get_device_id(self) -> str | None:
        """Get device ID (did) for the configured device.

        Returns:
            Device ID string or None if device not found
        """
        if self._device_info:
            return self._device_info.get("did")

        device = await self.find_device()
        if device:
            return device.get("did")

        return None

    async def play_tts(self, text: str) -> bool:
        """Play TTS on the device.

        Args:
            text: Text to speak

        Returns:
            True if successful
        """
        if not self._service_token:
            logger.error("MiOT not logged in")
            return False

        if not self._device_info:
            await self.find_device()

        if not self._device_info:
            logger.error("MiOT device not found")
            return False

        device_id = self._device_info.get("did")
        if not device_id:
            logger.error("MiOT device ID not found")
            return False

        try:
            url = f"{self.API_BASE}/v2/device/tts"
            nonce = self._generate_nonce()

            payload = {
                "did": device_id,
                "text": text,
                "nonce": nonce,
            }

            signed_payload = self._sign_payload(payload, url)

            response = await self._client.post(
                url,
                data=signed_payload,
                headers={"Authorization": f"Bearer {self._service_token}"},
            )
            result = response.json()

            if result.get("code") != 0:
                logger.error("MiOT TTS failed: {}", result.get("message"))
                return False

            logger.debug("MiOT TTS played: {}", text[:50])
            return True

        except Exception as e:
            logger.error("MiOT TTS error: {}", e)
            return False

    async def do_action(
        self,
        action: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Execute action on the device.

        Args:
            action: Action name (e.g., "tts_play")
            params: Action parameters

        Returns:
            Result dictionary or None if failed
        """
        if not self._service_token:
            logger.error("MiOT not logged in")
            return None

        if not self._device_info:
            await self.find_device()

        if not self._device_info:
            logger.error("MiOT device not found")
            return None

        device_id = self._device_info.get("did")
        if not device_id:
            logger.error("MiOT device ID not found")
            return None

        try:
            url = f"{self.API_BASE}/v2/device/action"
            nonce = self._generate_nonce()

            payload = {
                "did": device_id,
                "action": action,
                "params": json.dumps(params or {}),
                "nonce": nonce,
            }

            signed_payload = self._sign_payload(payload, url)

            response = await self._client.post(
                url,
                data=signed_payload,
                headers={"Authorization": f"Bearer {self._service_token}"},
            )
            result = response.json()

            if result.get("code") != 0:
                logger.error("MiOT action failed: {}", result.get("message"))
                return None

            return result.get("data")

        except Exception as e:
            logger.error("MiOT action error: {}", e)
            return None

    async def get_property(
        self,
        prop: str,
    ) -> dict[str, Any] | None:
        """Get device property.

        Args:
            prop: Property name

        Returns:
            Property value or None if failed
        """
        if not self._service_token:
            logger.error("MiOT not logged in")
            return None

        if not self._device_info:
            await self.find_device()

        if not self._device_info:
            logger.error("MiOT device not found")
            return None

        device_id = self._device_info.get("did")
        if not device_id:
            logger.error("MiOT device ID not found")
            return None

        try:
            url = f"{self.API_BASE}/v2/device/property"
            nonce = self._generate_nonce()

            payload = {
                "did": device_id,
                "props": prop,
                "nonce": nonce,
            }

            signed_payload = self._sign_payload(payload, url)

            response = await self._client.post(
                url,
                data=signed_payload,
                headers={"Authorization": f"Bearer {self._service_token}"},
            )
            result = response.json()

            if result.get("code") != 0:
                logger.error("MiOT get property failed: {}", result.get("message"))
                return None

            return result.get("data")

        except Exception as e:
            logger.error("MiOT get property error: {}", e)
            return None

    def _generate_nonce(self) -> str:
        """Generate a random nonce for API requests."""
        return md5(str(time.time()) + str(random.random()))[:16]

    def _sign_payload(self, payload: dict[str, Any], url: str) -> dict[str, Any]:
        """Sign the API request payload.

        Args:
            payload: Request payload
            url: Request URL

        Returns:
            Signed payload with signature
        """
        # Sort keys and create string
        sorted_payload = sorted(payload.items())
        payload_str = "&".join(f"{k}={v}" for k, v in sorted_payload)

        # Create signature
        signature = hmac.new(
            self._pass_token.encode(),
            payload_str.encode(),
            hashlib.sha256
        ).hexdigest()

        # Add signature to payload
        signed = dict(payload)
        signed["signature"] = signature

        return signed

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    @property
    def is_logged_in(self) -> bool:
        """Check if logged in."""
        return self._service_token is not None

    @property
    def device_id(self) -> str | None:
        """Get current device ID."""
        return self._device_id

    @property
    def device_info(self) -> dict[str, Any] | None:
        """Get current device info."""
        return self._device_info
