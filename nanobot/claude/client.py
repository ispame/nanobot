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
        logger.info(f"Starting Claude Code process with resume={resume}, session_id={self.session_id}, cwd={self.cwd}")
        args = [
            self.config.claude_path,
            "-p",  # Non-interactive print mode
            "--output-format", "stream-json",
            "--input-format", "stream-json",
            "--verbose",
        ]

        # Only use --resume if it's a valid UUID format
        import re
        uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
        if resume and uuid_pattern.match(resume):
            args.extend(["--resume", resume])
        elif self.session_id and uuid_pattern.match(self.session_id):
            args.extend(["--resume", self.session_id])

        # Only add model if explicitly configured (don't override user's default)
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

        logger.info(f"Starting Claude Code: {' '.join(args)}")

        # Set up environment - unset CLAUDECODE to avoid nested session error
        env = os.environ.copy()
        env["CLAUDE_CODE_ENTRYPOINT"] = "sdk-python"
        # Remove CLAUDECODE env var to allow subprocess to start its own session
        if "CLAUDECODE" in env:
            del env["CLAUDECODE"]
        if "CLAUDE_CODE" in env:
            del env["CLAUDE_CODE"]

        logger.info(f"Environment after cleanup: CLAUDECODE={'(not set)' if 'CLAUDECODE' not in env else env.get('CLAUDECODE')}")

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
        self._stderr = self._process.stderr

        # Start reading messages
        self._read_task = asyncio.create_task(self._read_messages())

        # Also read stderr for debugging
        if self._stderr:
            asyncio.create_task(self._read_stderr())

        # Wait for initialization to get session ID (with timeout)
        logger.info("Waiting for Claude Code initialization...")
        session_id = None
        try:
            # Wait for init message with timeout
            init_task = asyncio.create_task(self._wait_for_init())
            try:
                session_id = await asyncio.wait_for(init_task, timeout=30.0)
                logger.info(f"Claude Code initialized with session: {session_id}")
            except asyncio.TimeoutError:
                logger.error("Claude Code initialization timed out after 30 seconds")
        except Exception as e:
            logger.error(f"Error during Claude Code initialization: {e}")

        # Check if process is still running after init
        if self._process:
            logger.info(f"After initialization: returncode={self._process.returncode}")
            if self._process.returncode is not None:
                logger.error(f"Claude Code process exited during initialization with code {self._process.returncode}")

        return session_id or self.session_id or str(uuid.uuid4())

    async def _wait_for_init(self) -> str | None:
        """Wait for initialization message from Claude Code."""
        async for msg in self._stream_messages():
            msg_type = msg.get("type")
            subtype = msg.get("subtype")
            logger.info(f"Received message: {msg_type}, subtype: {subtype}")
            if msg_type == "system" and subtype == "init":
                return msg.get("session_id")
            # Log error messages for debugging
            if msg_type == "result" and subtype == "error_during_execution":
                logger.error(f"Claude Code error: {msg.get('message', msg)}")
        return None

    async def _read_stderr(self):
        """Read stderr from Claude Code process."""
        if not self._stderr:
            return
        try:
            while True:
                line = await self._stderr.readline()
                if not line:
                    break
                logger.info(f"Claude Code stderr: {line.decode('utf-8').strip()}")
        except Exception as e:
            logger.error(f"Error reading stderr: {e}")

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

        # Check if process is still running before sending
        if self._process and self._process.returncode is not None:
            raise RuntimeError(f"Process already exited with code {self._process.returncode}")

        logger.info(f"ClaudeCodeProcess.send_message: stdin={self._stdin}, subprocess={self._process}")
        if self._process:
            logger.info(f"ClaudeCodeProcess._process: returncode={self._process.returncode}")

        # Send user message
        message = {
            "type": "user",
            "message": {
                "role": "user",
                "content": content,
            },
        }
        self._stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        logger.info("Draining stdin...")
        await self._stdin.drain()
        logger.info("Drain complete, streaming responses...")

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
            try:
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    self._process.kill()
                    await self._process.wait()
            except ProcessLookupError:
                # Process already exited
                logger.debug("Process already exited, skipping terminate")


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
