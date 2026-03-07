"""Chat logic -对接 Nanobot AgentLoop"""

import asyncio
import json
from pathlib import Path
from typing import Optional, AsyncGenerator
import uuid

from loguru import logger

from app import get_config, get_nanobot_config, get_user_dir, get_user_memory_dir


class NanobotChat:
    """Nanobot chat handler for a single user."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self._agent = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize nanobot agent for this user."""
        if self._initialized:
            return

        try:
            # Import nanobot modules
            from nanobot.agent.loop import AgentLoop
            from nanobot.bus.queue import MessageBus
            from nanobot.config.loader import load_config
            from nanobot.session.manager import SessionManager
            from nanobot.utils.helpers import sync_workspace_templates
            from nanobot.providers.litellm_provider import LiteLLMProvider

            # Load nanobot config
            nanobot_config = get_nanobot_config()
            config_path = nanobot_config.get("config_path", Path.home() / ".nanobot" / "config.json")

            if not config_path.exists():
                raise FileNotFoundError(f"Nanobot config not found: {config_path}")

            config = load_config(config_path)
            workspace = nanobot_config.get("workspace_path", Path.home() / ".nanobot" / "workspace")

            # Create user-specific workspace
            user_dir = get_user_dir(self.user_id)
            user_workspace = user_dir / "workspace"
            user_workspace.mkdir(exist_ok=True)

            # Sync templates to user workspace
            sync_workspace_templates(user_workspace)

            # Create bus and provider
            bus = MessageBus()
            provider = self._create_provider(config)

            # Create session manager for this user
            session_manager = SessionManager(user_workspace)

            # Create agent
            self._agent = AgentLoop(
                bus=bus,
                provider=provider,
                workspace=user_workspace,
                model=config.agents.defaults.model,
                temperature=config.agents.defaults.temperature,
                max_tokens=config.agents.defaults.max_tokens,
                max_iterations=config.agents.defaults.max_tool_iterations,
                memory_window=config.agents.defaults.memory_window,
                reasoning_effort=config.agents.defaults.reasoning_effort,
                brave_api_key=config.tools.web.search.api_key or None,
                web_proxy=config.tools.web.proxy or None,
                exec_config=config.tools.exec,
                cron_service=None,
                restrict_to_workspace=config.tools.restrict_to_workspace,
                session_manager=session_manager,
                mcp_servers=config.tools.mcp_servers,
                channels_config=config.channels,
            )

            self._initialized = True
            logger.info(f"Nanobot chat initialized for user: {self.user_id}")

        except Exception as e:
            logger.exception(f"Failed to initialize nanobot for user {self.user_id}")
            raise RuntimeError(f"Failed to initialize chat: {e}")

    def _create_provider(self, config):
        """Create LLM provider from config."""
        from nanobot.providers.litellm_provider import LiteLLMProvider
        from nanobot.providers.custom_provider import CustomProvider
        from nanobot.providers.openai_codex_provider import OpenAICodexProvider

        model = config.agents.defaults.model
        provider_name = config.get_provider_name(model)
        p = config.get_provider(model)

        # OpenAI Codex (OAuth)
        if provider_name == "openai_codex" or model.startswith("openai-codex/"):
            return OpenAICodexProvider(default_model=model)

        # Custom: direct OpenAI-compatible endpoint
        if provider_name == "custom":
            return CustomProvider(
                api_key=p.api_key if p else "no-key",
                api_base=config.get_api_base(model) or "http://localhost:8000/v1",
                default_model=model,
            )

        return LiteLLMProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
            provider_name=provider_name,
        )

    async def chat(
        self,
        message: str,
        session_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Send a message and yield response chunks."""
        if not self._initialized:
            await self.initialize()

        # Generate session ID if not provided
        if session_id is None:
            session_id = f"web:{uuid.uuid4().hex[:8]}"

        session_key = f"web:{self.user_id}:{session_id}"

        # Use queue to collect progress updates for streaming
        progress_queue: asyncio.Queue[str] = asyncio.Queue()

        async def progress_callback(content: str, *, tool_hint: bool = False) -> None:
            await progress_queue.put(content)

        # Start processing in background
        process_task = asyncio.create_task(
            self._agent.process_direct(
                content=message,
                session_key=session_key,
                channel="web",
                chat_id=self.user_id,
                on_progress=progress_callback,
            )
        )

        # Stream progress updates as they come in
        full_response = ""
        while not process_task.done() or not progress_queue.empty():
            try:
                chunk = await asyncio.wait_for(progress_queue.get(), timeout=0.1)
                full_response += chunk
                yield chunk
            except asyncio.TimeoutError:
                continue

        # Get any remaining response
        remaining = await process_task
        if remaining and remaining not in full_response:
            full_response += remaining
            yield remaining

    async def close(self) -> None:
        """Close the agent."""
        if self._agent:
            await self._agent.close_mcp()
            self._agent.stop()
            self._initialized = False


# Global agent cache
_chat_cache: dict[str, NanobotChat] = {}


async def get_chat(user_id: str) -> NanobotChat:
    """Get or create a chat handler for a user."""
    if user_id not in _chat_cache:
        _chat_cache[user_id] = NanobotChat(user_id)
    return _chat_cache[user_id]


async def close_all_chats() -> None:
    """Close all chat handlers."""
    for chat in _chat_cache.values():
        await chat.close()
    _chat_cache.clear()
