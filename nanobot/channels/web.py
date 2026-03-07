"""Web chat channel for nanobot gateway."""

import asyncio
import json
import secrets
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import WebChannelConfig


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class RegisterRequest(BaseModel):
    user_id: str
    password: str


class LoginRequest(BaseModel):
    user_id: str
    password: str


# Auth utilities (adapted from web_chat)
def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    """Hash a password with a random salt."""
    import hashlib

    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100000,
    )
    return hashed.hex(), salt


def verify_password(password: str, hashed: str, salt: str) -> bool:
    """Verify a password against its hash."""
    new_hash, _ = hash_password(password, salt)
    return new_hash == hashed


def get_allowed_ids(config: WebChannelConfig) -> list[str]:
    """Get list of allowed user IDs."""
    return config.allowed_ids


def get_admin_ids(config: WebChannelConfig) -> list[str]:
    """Get list of admin IDs."""
    return config.admin_ids


def is_allowed_id(user_id: str, config: WebChannelConfig) -> bool:
    """Check if user ID is allowed to register."""
    allowed = get_allowed_ids(config)
    if not allowed:  # If empty, allow all
        return True
    return user_id in allowed


def is_admin(user_id: str, config: WebChannelConfig) -> bool:
    """Check if user is an admin."""
    return user_id in get_admin_ids(config)


# User data storage
def _get_users_dir(config: WebChannelConfig) -> Path:
    """Get users directory path."""
    # Store in workspace for persistence
    workspace = Path(config.nanobot_workspace_path).expanduser()
    users_dir = workspace / "web_chat_users"
    users_dir.mkdir(parents=True, exist_ok=True)
    return users_dir


def _get_user_dir(user_id: str, config: WebChannelConfig) -> Path:
    """Get a specific user's directory."""
    users_dir = _get_users_dir(config)
    user_dir = users_dir / user_id
    user_dir.mkdir(exist_ok=True)
    return user_dir


def get_user_data(user_id: str, config: WebChannelConfig) -> Optional[dict]:
    """Get user data from storage."""
    user_file = _get_user_dir(user_id, config) / "user.json"
    if not user_file.exists():
        return None
    with open(user_file, "r", encoding="utf-8") as f:
        return json.load(f)


def save_user_data(user_id: str, data: dict, config: WebChannelConfig) -> None:
    """Save user data to storage."""
    user_file = _get_user_dir(user_id, config) / "user.json"
    with open(user_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def register_user(user_id: str, password: str, config: WebChannelConfig) -> bool:
    """Register a new user."""
    # Check if user already exists
    if get_user_data(user_id, config) is not None:
        raise Exception("User already exists")

    # Check if ID is allowed
    if not is_allowed_id(user_id, config):
        raise Exception("User ID not allowed to register")

    # Hash password
    hashed, salt = hash_password(password)

    # Save user data
    save_user_data(user_id, {
        "user_id": user_id,
        "password_hash": hashed,
        "salt": salt,
        "is_admin": is_admin(user_id, config),
    }, config)

    # Initialize user files
    _initialize_user_files(user_id, config)

    return True


def authenticate(user_id: str, password: str, config: WebChannelConfig) -> bool:
    """Authenticate a user."""
    user_data = get_user_data(user_id, config)
    if user_data is None:
        return False

    return verify_password(
        password,
        user_data["password_hash"],
        user_data["salt"]
    )


def _initialize_user_files(user_id: str, config: WebChannelConfig) -> None:
    """Initialize user's memory and soul files."""
    user_dir = _get_user_dir(user_id, config)

    # Create soul.md if not exists
    soul_file = user_dir / "soul.md"
    if not soul_file.exists():
        soul_file.write_text(
            f"# {user_id}'s Soul\n\n"
            f"This is {user_id}'s personal AI assistant.\n\n"
            "## Preferences\n\n- Communication style: [Describe your preferences]\n- Interests: [List your interests]\n- Background: [Your background info]\n",
            encoding="utf-8"
        )

    # Create memory directory
    memory_dir = user_dir / "memory"
    memory_dir.mkdir(exist_ok=True)

    # Create MEMORY.md if not exists
    memory_file = memory_dir / "MEMORY.md"
    if not memory_file.exists():
        memory_file.write_text(
            f"# {user_id}'s Long-term Memory\n\n"
            f"This is {user_id}'s persistent memory.\n",
            encoding="utf-8"
        )

    # Create HISTORY.md if not exists
    history_file = memory_dir / "HISTORY.md"
    if not history_file.exists():
        history_file.write_text(
            f"# {user_id}'s Conversation History\n\n",
            encoding="utf-8"
        )


# NanobotChat for WebChannel
class NanobotWebChat:
    """Nanobot chat handler for a single web user."""

    def __init__(self, user_id: str, config: WebChannelConfig):
        self.user_id = user_id
        self.config = config
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
            config_path = Path(self.config.nanobot_config_path).expanduser()
            if not config_path.exists():
                raise FileNotFoundError(f"Nanobot config not found: {config_path}")

            from nanobot.config.schema import Config
            config_obj = Config.model_validate_json(config_path.read_text())

            # Create user-specific workspace
            user_dir = _get_user_dir(self.user_id, self.config)
            user_workspace = user_dir / "workspace"
            user_workspace.mkdir(exist_ok=True)

            # Sync templates to user workspace
            sync_workspace_templates(user_workspace)

            # Create bus and provider
            bus = MessageBus()
            provider = self._create_provider(config_obj)

            # Create session manager for this user
            session_manager = SessionManager(user_workspace)

            # Create agent
            self._agent = AgentLoop(
                bus=bus,
                provider=provider,
                workspace=user_workspace,
                model=config_obj.agents.defaults.model,
                temperature=config_obj.agents.defaults.temperature,
                max_tokens=config_obj.agents.defaults.max_tokens,
                max_iterations=config_obj.agents.defaults.max_tool_iterations,
                memory_window=config_obj.agents.defaults.memory_window,
                reasoning_effort=config_obj.agents.defaults.reasoning_effort,
                brave_api_key=config_obj.tools.web.search.api_key or None,
                web_proxy=config_obj.tools.web.proxy or None,
                exec_config=config_obj.tools.exec,
                cron_service=None,
                restrict_to_workspace=config_obj.tools.restrict_to_workspace,
                session_manager=session_manager,
                mcp_servers=config_obj.tools.mcp_servers,
                channels_config=config_obj.channels,
            )

            self._initialized = True
            logger.info(f"Nanobot web chat initialized for user: {self.user_id}")

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
        import uuid

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


# Global chat cache
_chat_cache: dict[str, NanobotWebChat] = {}


async def get_web_chat(user_id: str, config: WebChannelConfig) -> NanobotWebChat:
    """Get or create a chat handler for a user."""
    cache_key = f"{config.port}:{user_id}"
    if cache_key not in _chat_cache:
        _chat_cache[cache_key] = NanobotWebChat(user_id, config)
    return _chat_cache[cache_key]


async def close_all_web_chats() -> None:
    """Close all chat handlers."""
    for chat in _chat_cache.values():
        await chat.close()
    _chat_cache.clear()


# WebChannel class
class WebChannel(BaseChannel):
    """Web chat channel for nanobot gateway."""

    name = "web"

    def __init__(self, config: WebChannelConfig, bus: MessageBus):
        super().__init__(config, bus)
        self._app: Optional[FastAPI] = None
        self._server_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

    @asynccontextmanager
    async def _lifespan(self, app: FastAPI):
        """Lifespan context manager for startup/shutdown."""
        yield
        # Cleanup on shutdown
        await close_all_web_chats()

    def _create_app(self) -> FastAPI:
        """Create FastAPI application."""
        app = FastAPI(title="Nanobot Web Chat", lifespan=self._lifespan)

        # Add session middleware
        app.add_middleware(
            SessionMiddleware,
            secret_key=self.config.session_secret,
        )

        # Add CORS middleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Setup templates
        template_dir = Path(__file__).parent.parent.parent / "web_chat" / "app" / "templates"
        if template_dir.exists():
            templates = Jinja2Templates(directory=template_dir)
        else:
            templates = None

        # Dependency: Get current user
        def get_current_user(request: Request) -> Optional[str]:
            """Get current logged-in user from session."""
            return request.session.get("user_id")

        def require_auth(user_id: Optional[str] = None) -> str:
            """Require authentication."""
            if not user_id:
                raise HTTPException(status_code=401, detail="Not authenticated")
            return user_id

        # Routes
        @app.get("/", response_class=HTMLResponse)
        async def root(request: Request):
            if templates:
                user_id = get_current_user(request)
                if user_id:
                    return templates.TemplateResponse("chat.html", {"request": request, "user_id": user_id})
                return templates.TemplateResponse("login.html", {"request": request})
            return {"status": "ok", "message": "Nanobot Web Chat"}

        @app.get("/chat", response_class=HTMLResponse)
        async def chat_page(request: Request):
            if not templates:
                raise HTTPException(status_code=404, detail="Templates not found")
            user_id = get_current_user(request)
            if not user_id:
                return templates.TemplateResponse("login.html", {"request": request})
            return templates.TemplateResponse("chat.html", {"request": request, "user_id": user_id})

        @app.get("/login", response_class=HTMLResponse)
        async def login_page(request: Request):
            if not templates:
                raise HTTPException(status_code=404, detail="Templates not found")
            return templates.TemplateResponse("login.html", {"request": request})

        @app.get("/register", response_class=HTMLResponse)
        async def register_page(request: Request):
            if not templates:
                raise HTTPException(status_code=404, detail="Templates not found")
            allowed_ids = get_allowed_ids(self.config)
            return templates.TemplateResponse(
                "register.html",
                {"request": request, "allowed_ids": allowed_ids}
            )

        # API Routes
        @app.post("/api/register")
        async def register(req: RegisterRequest):
            try:
                register_user(req.user_id, req.password, self.config)
                return {"success": True, "message": "Registration successful"}
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))

        @app.post("/api/login")
        async def login(req: LoginRequest, request: Request):
            if authenticate(req.user_id, req.password, self.config):
                request.session["user_id"] = req.user_id
                return {"success": True, "redirect": "/chat"}
            raise HTTPException(status_code=401, detail="Invalid credentials")

        @app.post("/api/logout")
        async def logout(request: Request):
            request.session.clear()
            return {"success": True, "redirect": "/login"}

        @app.get("/api/user")
        async def get_user(request: Request):
            user_id = get_current_user(request)
            if not user_id:
                raise HTTPException(status_code=401, detail="Not authenticated")
            user_data = get_user_data(user_id, self.config)
            if not user_data:
                raise HTTPException(status_code=404, detail="User not found")
            return {
                "user_id": user_data["user_id"],
                "is_admin": user_data.get("is_admin", False),
            }

        @app.post("/api/chat")
        async def send_message(req: ChatRequest, request: Request):
            user_id = get_current_user(request)
            if not user_id:
                raise HTTPException(status_code=401, detail="Not authenticated")

            try:
                nanobot_chat = await get_web_chat(user_id, self.config)

                # Collect full response
                full_response = ""
                async for chunk in nanobot_chat.chat(req.message, req.session_id):
                    full_response += chunk

                return {"response": full_response}
            except Exception as e:
                logger.exception(f"Error in chat: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @app.post("/api/chat/stream")
        async def stream_message(req: ChatRequest, request: Request):
            user_id = get_current_user(request)
            if not user_id:
                raise HTTPException(status_code=401, detail="Not authenticated")

            async def generate():
                try:
                    nanobot_chat = await get_web_chat(user_id, self.config)
                    async for chunk in nanobot_chat.chat(req.message, req.session_id):
                        yield f"data: {json.dumps({'chunk': chunk})}\n\n"
                    yield f"data: {json.dumps({'done': True})}\n\n"
                except Exception as e:
                    logger.exception(f"Error in stream chat: {e}")
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"

            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
            )

        return app

    async def start(self) -> None:
        """Start the web chat server."""
        logger.info(f"Starting web chat channel on {self.config.host}:{self.config.port}")

        self._app = self._create_app()

        # Run uvicorn in a separate thread/task
        config = uvicorn.Config(
            self._app,
            host=self.config.host,
            port=self.config.port,
            log_level="info",
        )
        server = uvicorn.Server(config)

        # Run server in background
        self._server_task = asyncio.create_task(server.serve())
        self._running = True

        logger.info(f"Web chat channel started on http://{self.config.host}:{self.config.port}")

    async def stop(self) -> None:
        """Stop the web chat server."""
        logger.info("Stopping web chat channel...")
        self._running = False

        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass

        await close_all_web_chats()
        logger.info("Web chat channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """
        Send a message through the web channel.

        Note: For web chat, outbound messages are typically sent as streaming
        responses to chat requests. This method handles any push notifications
        or deferred messages if needed.
        """
        # For the current web chat architecture, messages are sent as
        # streaming responses to HTTP requests. This method handles
        # any out-of-band messages if needed.
        logger.debug(f"Web channel send: {msg.content[:50]}...")
