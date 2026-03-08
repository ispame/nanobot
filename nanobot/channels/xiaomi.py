"""Xiaomi (Xiao AI) speaker channel implementation."""

import asyncio
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import XiaomiConfig

try:
    from nanobot.services.miot import MiOTService

    MIOT_AVAILABLE = True
except ImportError:
    MIOT_AVAILABLE = False
    MiOTService = None


class ResponseRouter:
    """Determine response output channel based on content complexity."""

    @staticmethod
    def should_use_tts(content: str, threshold: int = 100) -> bool:
        """
        Determine if response should use TTS or Feishu.

        Args:
            content: The response content.
            threshold: Max length for TTS response.

        Returns:
            True if TTS should be used, False for Feishu.
        """
        # 1. Short text -> TTS
        if len(content) < threshold:
            return True

        # 2. Complex content indicators -> Feishu
        complex_indicators = ["```", "|", "\n- ", "\n1. ", "\n2. "]
        if any(indicator in content for indicator in complex_indicators):
            return False

        # 3. Default: short enough for TTS
        return len(content) < threshold * 2


class XiaomiChannel(BaseChannel):
    """Xiaomi Xiao AI speaker channel using MiOT service."""

    name = "xiaomi"

    def __init__(self, config: XiaomiConfig, bus: MessageBus, groq_api_key: str | None = None):
        super().__init__(config, bus)
        self.config: XiaomiConfig = config
        self.groq_api_key = groq_api_key
        self._miot: MiOTService | None = None
        self._running = False
        self._poll_task: asyncio.Task | None = None
        self._last_voice_id: str = ""
        self._transcriber = None

    async def start(self) -> None:
        """Start the Xiaomi channel and begin polling for voice input."""
        if not MIOT_AVAILABLE:
            logger.error("MiOT service not available. Please ensure httpx is installed.")
            return

        if not self.config.user_id or not self.config.pass_token:
            logger.error("Xiaomi: userId and passToken not configured")
            return

        if not self.config.device_name:
            logger.error("Xiaomi: deviceName not configured")
            return

        # Initialize MiOT service
        try:
            self._miot = MiOTService(
                user_id=self.config.user_id,
                pass_token=self.config.pass_token,
                device_name=self.config.device_name,
            )

            # Login to Xiaomi account
            login_success = await self._miot.login()
            if not login_success:
                logger.error("Xiaomi: Failed to login to Xiaomi account")
                return

            # Find the device
            device = await self._miot.find_device()
            if not device:
                logger.error("Xiaomi: Device not found: {}", self.config.device_name)
                return

            logger.info(
                "Xiaomi: Connected to device: {} (did: {})",
                device.get("name"),
                device.get("did")
            )

        except Exception as e:
            logger.error("Xiaomi: Failed to initialize: {}", e)
            return

        # Initialize transcription provider
        if self.groq_api_key:
            from nanobot.providers.transcription import GroqTranscriptionProvider
            self._transcriber = GroqTranscriptionProvider(self.groq_api_key)

        self._running = True
        self._poll_task = asyncio.create_task(self._poll_voice_input())

        logger.info("Xiaomi: Channel started")

    async def stop(self) -> None:
        """Stop the Xiaomi channel."""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        if self._miot:
            await self._miot.close()

        logger.info("Xiaomi: Channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """
        Send a message - either via TTS or Feishu based on content complexity.
        """
        if not self._miot or not self._miot.is_logged_in:
            logger.warning("Xiaomi: Not connected")
            return

        content = msg.content or ""

        # Check if should use TTS or Feishu
        use_tts = ResponseRouter.should_use_tts(
            content,
            self.config.simple_response_length_threshold
        )

        if use_tts:
            await self._send_via_tts(content)
        else:
            await self._send_via_feishu(msg)

    async def _send_via_tts(self, content: str) -> None:
        """Send content via TTS on the Xiaomi speaker."""
        if not self._miot:
            return

        try:
            # Use MiOT TTS
            success = await self._miot.play_tts(content)
            if success:
                logger.debug("Xiaomi: TTS played: {} chars", len(content))
            else:
                logger.error("Xiaomi: TTS playback failed")
        except Exception as e:
            logger.error("Xiaomi: TTS error: {}", e)

    async def _send_via_feishu(self, msg: OutboundMessage) -> None:
        """Forward complex message to Feishu channel."""
        if not self.config.feishu_reply_enabled:
            logger.debug("Xiaomi: Feishu reply disabled, skipping")
            return

        # Create new OutboundMessage for Feishu
        # Use metadata to pass through original sender info
        feishu_msg = OutboundMessage(
            channel="feishu",
            chat_id=msg.metadata.get("feishu_chat_id", ""),
            content=msg.content,
            media=msg.media,
            metadata=msg.metadata,
        )

        # Publish to bus - the dispatcher will route to feishu
        await self.bus.publish_outbound(feishu_msg)
        logger.debug("Xiaomi: Forwarded to Feishu: {} chars", len(msg.content))

    async def _poll_voice_input(self) -> None:
        """Poll for voice input from the Xiaomi speaker."""
        while self._running:
            try:
                await self._check_voice_input()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Xiaomi: Poll error: {}", e)

            await asyncio.sleep(self.config.poll_interval_seconds)

    async def _check_voice_input(self) -> None:
        """Check for new voice input and process if available."""
        # Note: The actual implementation depends on how we get voice data
        # This is a placeholder that checks the device status
        # In practice, we'd need to:
        # 1. Use voice备忘 API or custom skill to trigger recording
        # 2. Get the recorded audio file
        # 3. Transcribe and process

        if not self._miot:
            return

        # TODO: Implement actual voice input detection
        # This typically requires:
        # 1. Setting up a custom voice command that triggers HTTP callback
        # 2. Or polling the device's voice memo API
        # 3. Or using the MiOT voice recording functionality

        logger.trace("Xiaomi: Checking for voice input...")

    async def _process_voice_input(self, audio_path: str) -> None:
        """Process voice input: transcribe and send to message bus."""
        if not self._transcriber:
            logger.warning("Xiaomi: No transcription provider configured")
            return

        try:
            # Transcribe audio
            transcription = await self._transcriber.transcribe(audio_path)
            if not transcription:
                logger.warning("Xiaomi: Empty transcription")
                return

            logger.info("Xiaomi: Transcribed: {}", transcription)

            # Send to message bus
            await self._handle_message(
                sender_id="default",
                chat_id="default",
                content=transcription,
                metadata={"source": "xiaomi_voice"},
            )

        except Exception as e:
            logger.error("Xiaomi: Voice processing error: {}", e)

    async def _get_voice_recording(self) -> str | None:
        """
        Get the latest voice recording from the device.

        Returns:
            Path to temporary audio file, or None if no recording available.
        """
        # This is a placeholder - actual implementation depends on
        # the specific Xiaomi device capabilities and API access
        #
        # Possible approaches:
        # 1. Use MiOT's get_file to fetch voice memos
        # 2. Use custom skill that saves recordings to accessible location
        # 3. Use HTTP callback for custom voice commands

        return None
