"""Nanobot Web Chat - Main Entry Point"""

import argparse
import json
import os
import sys
from pathlib import Path

import uvicorn


def load_config(config_path: str = "config.json") -> dict:
    """Load configuration from JSON file."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def setup_nanobot_path(config: dict) -> str:
    """Setup nanobot path from config and add to sys.path."""
    # Default path for backward compatibility
    default_path = "/Users/spame/WorkTable/openclaw_coder/nanobot"

    nanobot_config = config.get("nanobot", {})
    nanobot_path = nanobot_config.get("path", default_path)

    # Expand ~ to user home
    nanobot_path = str(Path(nanobot_path).expanduser())

    if nanobot_path not in sys.path:
        sys.path.insert(0, nanobot_path)

    return nanobot_path


def main():
    parser = argparse.ArgumentParser(description="Nanobot Web Chat Server")
    parser.add_argument(
        "--config", "-c", default="config.json", help="Config file path"
    )
    parser.add_argument(
        "--host", "-H", default=None, help="Server host"
    )
    parser.add_argument(
        "--port", "-p", type=int, default=None, help="Server port"
    )
    parser.add_argument(
        "--reload", "-r", action="store_true", help="Auto-reload on code changes"
    )

    args = parser.parse_args()

    # Load config
    config = load_config(args.config)

    # Get server settings
    host = args.host or config.get("server", {}).get("host", "0.0.0.0")
    port = args.port or config.get("server", {}).get("port", 8000)

    # Store config in environment for app to access
    os.environ["NANOBOT_WEB_CONFIG"] = json.dumps(config)

    # Setup nanobot path
    nanobot_path = setup_nanobot_path(config)
    print(f"Using Nanobot from: {nanobot_path}")

    print(f"Starting Nanobot Web Chat on {host}:{port}")
    print(f"Chat interface: http://{host if host != '0.0.0.0' else 'localhost'}:{port}/chat")

    # Add app directory to path for uvicorn
    app_dir = str(Path(__file__).parent)
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)

    uvicorn.run(
        "app.app:app",
        host=host,
        port=port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
