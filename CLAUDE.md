# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

nanobot is an ultra-lightweight (~4,000 lines) personal AI assistant framework. It connects LLMs to multiple chat platforms (Telegram, Discord, Feishu, Slack, etc.) and provides a tool-augmented agent loop for autonomous task execution.

## Common Commands

```bash
# Development
pip install -e .                    # Install in editable mode
pip install -e ".[dev]"             # Install with dev dependencies (includes pytest, ruff)

# Linting
ruff check nanobot/                 # Run linter
ruff format nanobot/                # Format code

# Testing
pytest                              # Run all tests
pytest tests/test_name.py           # Run specific test file
pytest -k "test_pattern"           # Run tests matching pattern

# Running
nanobot onboard                     # Initialize config & workspace
nanobot agent -m "Hello!"           # Chat with agent
nanobot agent                       # Interactive mode
nanobot gateway                     # Start gateway (connects to all enabled channels)
nanobot status                      # Show status
nanobot channels login              # Link WhatsApp (QR scan)
nanobot provider login openai-codex # OAuth login for providers

# Docker
docker compose up -d nanobot-gateway  # Start gateway in Docker
docker build -t nanobot .              # Build image
```

## Architecture

```
nanobot/
├── agent/           # Core agent logic
│   ├── loop.py      # LLM ↔ tool execution loop (the brain)
│   ├── context.py   # Prompt builder (system prompt + history)
│   ├── memory.py    # Persistent memory store
│   ├── skills.py    # Skills loader
│   ├── subagent.py  # Background task execution
│   └── tools/       # Built-in tools (filesystem, shell, message, web, etc.)
├── channels/        # Chat platform integrations
│   ├── telegram.py, discord.py, feishu.py, slack.py, ...
│   └── manager.py   # Channel lifecycle management
├── providers/       # LLM provider abstraction
│   ├── registry.py  # Provider metadata (adding new providers: 2 steps!)
│   ├── litellm_provider.py  # LiteLLM wrapper
│   └── custom_provider.py   # Direct OpenAI-compatible
├── bus/            # Message routing between channels and agent
├── cron/           # Scheduled task execution
├── heartbeat/      # Periodic wake-up for proactive tasks
├── session/        # Conversation session management
├── config/         # Configuration loading and schema
└── cli/           # CLI commands (typer-based)
```

### Key Concepts

- **Message Bus**: Routes messages between channels and the agent loop
- **Provider Registry**: Single source of truth for LLM providers (`nanobot/providers/registry.py`). Adding a new provider requires 2 steps: add `ProviderSpec` to registry + add config field to schema.
- **Skills**: Markdown-based agent capabilities loaded from `nanobot/skills/` and workspace
- **Heartbeat**: Agent wakes periodically to check `HEARTBEAT.md` for proactive tasks

### Provider Detection

Providers are auto-detected via:
1. Config key (e.g., `"provider": "dashscope"`)
2. API key prefix (e.g., `"sk-or-"` → OpenRouter)
3. API base URL keyword (e.g., `"aihubmix"` → AiHubMix)

## Configuration

- Config file: `~/.nanobot/config.json`
- Workspace: `~/.nanobot/workspace/` (contains HEARTBEAT.md, SOUL.md, USER.md, AGENTS.md, TOOLS.md)

### Security Note

In `v0.1.4.post3` and earlier, empty `allowFrom` means "allow all". In newer versions (including source builds), **empty `allowFrom` denies all access** — set `["*"]` to explicitly allow everyone.

## Testing

Tests use pytest with `asyncio_mode = auto`. Run specific tests with:
```bash
pytest tests/test_loop_save_turn.py -v
pytest -k "memory"  # Run tests matching "memory"
```
