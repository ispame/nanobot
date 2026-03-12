"""Claude Code SDK client wrapper for nanobot.

This module provides a Python interface to Claude Code CLI, communicating via
stdin/stdout using JSON messages (stream-json format).
"""

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import AsyncGenerator

from loguru import logger

from nanobot.config.schema import ClaudeCodeConfig


class ClaudeCodeProcess:
    """Manages a Claude Code subprocess for remote control."""

    def __init__(
        self,
        config: ClaudeCodeConfig,
        cwd: str | None = None,
        session_id: str | None = None,
    ):
        self.config = config
        self.cwd = cwd or os.getcwd()
        self.session_id = session_id
        self._process: asyncio.subprocess.Process | None = None
        self._stdin: asyncio.StreamWriter | None = None
        self._stdout: asyncio.StreamReader | None = None
        self._message_queue: asyncio.Queue[dict] = asyncio.Queue()
        self._read_task: asyncio.Task | None = None

    async def start(self, resume: str | None = None) -> str:
        """Start the Claude Code process and return the session ID."""
        args = [
            self.config.claude_path,
            "--output-format", "stream-json",
            "--verbose",
        ]

        if resume:
            args.extend(["--resume", resume])
        elif self.session_id:
            args.extend(["--resume", self.session_id])

        if self.config.default_model:
            args.extend(["--model", self.config.default_model])

        if self.config.permission_mode:
            args.extend(["--permission-mode", self.config.permission_mode])

        if self.config.allowed_tools:
            args.extend(["--allowed-tools", ",".join(self.config.allowed_tools)])

        if self.config.disallowed_tools:
            args.extend(["--disallowed-tools", ",".join(self.config.disallowed_tools)])

        # Add MCP servers if configured
        if self.config.mcp_servers:
            mcp_config = {
                "mcpServers": {
                    name: {
                        "command": server.command,
                        "args": server.args,
                        "env": server.env,
                    }
                    for name, server in self.config.mcp_servers.items()
                }
            }
            args.extend(["--mcp-config", json.dumps(mcp_config)])

        logger.debug(f"Starting Claude Code: {' '.join(args)}")

        # Set up environment
        env = os.environ.copy()
        env["CLAUDE_CODE_ENTRYPOINT"] = "sdk-python"

        self._process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.cwd,
            env=env,
        )

        self._stdin = self._process.stdin
        self._stdout = self._process.stdout

        # Start reading messages
        self._read_task = asyncio.create_task(self._read_messages())

        # Wait for initialization to get session ID
        session_id = None
        async for msg in self._stream_messages():
            if msg.get("type") == "system" and msg.get("subtype") == "init":
                session_id = msg.get("session_id")
                break

        return session_id or self.session_id or str(uuid.uuid4())

    async def _read_messages(self):
        """Continuously read messages from Claude Code stdout."""
        if not self._stdout:
            return

        try:
            while True:
                line = await self._stdout.readline()
                if not line:
                    break

                try:
                    msg = json.loads(line.decode("utf-8"))
                    await self._message_queue.put(msg)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # Skip non-JSON lines
                    pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error reading Claude Code output: {e}")

    async def _stream_messages(self) -> AsyncGenerator[dict, None]:
        """Stream messages from the queue."""
        while True:
            try:
                msg = await asyncio.wait_for(self._message_queue.get(), timeout=1.0)
                yield msg
            except asyncio.TimeoutError:
                if self._process and self._process.returncode is not None:
                    break

    async def send_message(self, content: str) -> AsyncGenerator[dict, None]:
        """Send a message to Claude Code and yield responses."""
        if not self._stdin:
            raise RuntimeError("Process not started")

        # Send user message
        message = {
            "type": "user",
            "message": {
                "role": "user",
                "content": content,
            },
        }
        self._stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        await self._stdin.drain()

        # Stream responses
        async for msg in self._stream_messages():
            yield msg

            if msg.get("type") == "result":
                break

    async def send_control_request(self, request: dict) -> dict:
        """Send a control request and wait for response."""
        if not self._stdin:
            raise RuntimeError("Process not started")

        request_id = str(uuid.uuid4())[:8]
        control_request = {
            "request_id": request_id,
            "type": "control_request",
            "request": request,
        }

        self._stdin.write((json.dumps(control_request) + "\n").encode("utf-8"))
        await self._stdin.drain()

        # Wait for response
        while True:
            msg = await self._message_queue.get()
            if (
                msg.get("type") == "control_response"
                and msg.get("response", {}).get("request_id") == request_id
            ):
                return msg.get("response", {})

    async def interrupt(self) -> None:
        """Send interrupt signal to Claude Code."""
        if not self._stdin:
            return

        request = {"subtype": "interrupt"}
        try:
            await self.send_control_request(request)
        except Exception as e:
            logger.debug(f"Interrupt error: {e}")

    async def close(self) -> None:
        """Close the Claude Code process."""
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()


class ClaudeClient:
    """Client for managing Claude Code sessions."""

    def __init__(self, config: ClaudeCodeConfig):
        self.config = config
        self._sessions: dict[str, ClaudeCodeProcess] = {}

    async def create_session(
        self, session_id: str | None = None, cwd: str | None = None
    ) -> ClaudeCodeProcess:
        """Create a new Claude Code session."""
        sid = session_id or str(uuid.uuid4())
        process = ClaudeCodeProcess(self.config, cwd=cwd, session_id=sid)
        actual_session_id = await process.start()
        self._sessions[actual_session_id] = process
        logger.info(f"Created Claude Code session: {actual_session_id}")
        return process

    async def get_or_create_session(
        self, session_id: str | None = None, cwd: str | None = None
    ) -> tuple[ClaudeCodeProcess, str]:
        """Get existing session or create a new one."""
        if session_id and session_id in self._sessions:
            return self._sessions[session_id], session_id

        process = await self.create_session(session_id, cwd)
        return process, process.session_id

    async def close_session(self, session_id: str) -> None:
        """Close a specific session."""
        if session_id in self._sessions:
            await self._sessions[session_id].close()
            del self._sessions[session_id]
            logger.info(f"Closed Claude Code session: {session_id}")

    async def close_all(self) -> None:
        """Close all sessions."""
        for session_id in list(self._sessions.keys()):
            await self.close_session(session_id)
