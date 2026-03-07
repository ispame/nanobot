"""FastAPI Application for Nanobot Web Chat"""

import os
import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from app import get_config
from app import auth
from app import chat as chat_module


# Create FastAPI app
app = FastAPI(title="Nanobot Web Chat", debug=False)

# Get session secret from config
_config = get_config()
_session_secret = _config.get("server", {}).get("session_secret", "dev-secret-change-me")

# Add session middleware
app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret,
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
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


# Dependency: Get current user
def get_current_user(request: Request) -> Optional[str]:
    """Get current logged-in user from session."""
    return request.session.get("user_id")


def require_auth(user_id: Optional[str] = Depends(get_current_user)) -> str:
    """Require authentication."""
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id


# Routes
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Redirect to chat page."""
    user_id = get_current_user(request)
    if user_id:
        return templates.TemplateResponse("chat.html", {"request": request, "user_id": user_id})
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    """Chat page."""
    user_id = get_current_user(request)
    if not user_id:
        return templates.TemplateResponse("login.html", {"request": request})
    return templates.TemplateResponse("chat.html", {"request": request, "user_id": user_id})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page."""
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """Registration page."""
    allowed_ids = auth.get_allowed_ids()
    return templates.TemplateResponse(
        "register.html",
        {"request": request, "allowed_ids": allowed_ids}
    )


# API Routes
class RegisterRequest(BaseModel):
    user_id: str
    password: str


class LoginRequest(BaseModel):
    user_id: str
    password: str


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


@app.post("/api/register")
async def register(req: RegisterRequest):
    """Register a new user."""
    try:
        auth.register_user(req.user_id, req.password)
        return {"success": True, "message": "Registration successful"}
    except auth.AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/login")
async def login(req: LoginRequest, request: Request):
    """Login user."""
    if auth.authenticate(req.user_id, req.password):
        request.session["user_id"] = req.user_id
        return {"success": True, "redirect": "/chat"}
    raise HTTPException(status_code=401, detail="Invalid credentials")


@app.post("/api/logout")
async def logout(request: Request):
    """Logout user."""
    request.session.clear()
    return {"success": True, "redirect": "/login"}


@app.get("/api/user")
async def get_user(user_id: str = Depends(require_auth)):
    """Get current user info."""
    user_data = auth.get_user_data(user_id)
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "user_id": user_data["user_id"],
        "is_admin": user_data.get("is_admin", False),
    }


@app.post("/api/chat")
async def send_message(
    req: ChatRequest,
    user_id: str = Depends(require_auth),
):
    """Send a message and get response."""
    try:
        nanobot_chat = await chat_module.get_chat(user_id)

        # Collect full response
        full_response = ""
        async for chunk in nanobot_chat.chat(req.message, req.session_id):
            full_response += chunk

        return {"response": full_response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/stream")
async def stream_message(
    req: ChatRequest,
    user_id: str = Depends(require_auth),
):
    """Send a message and stream response."""
    from fastapi.responses import StreamingResponse

    async def generate():
        try:
            nanobot_chat = await chat_module.get_chat(user_id)
            async for chunk in nanobot_chat.chat(req.message, req.session_id):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
    )


# Startup and shutdown
@app.on_event("startup")
async def startup_event():
    """Initialize on startup."""
    # Suppress loguru warnings
    logger = chat_module.logger
    # Configure logging


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    await chat_module.close_all_chats()


# Error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions."""
    if exc.status_code == 401:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Please login first"},
            status_code=401,
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )
