#!/usr/bin/env python3
"""
Test script for Xiaomi login.

Usage:
    python test_login.py
"""

import os
import sys
import json

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from xiaomi_auth import XiaomiAuth, save_credentials


def load_config():
    """Load configuration from .mi.json if exists."""
    mi_json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".mi.json")

    if os.path.exists(mi_json_path):
        try:
            with open(mi_json_path, "r") as f:
                config = json.load(f)
                return config.get("mina", {})
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def test_login():
    """Test the login flow."""
    print("=" * 40)
    print("Xiaomi Login Test")
    print("=" * 40)
    print()

    # Try to load existing credentials
    existing_config = load_config()
    user_id = existing_config.get("userId")
    password = existing_config.get("password")
    did = existing_config.get("did")

    # Override with test credentials or prompt
    if not user_id:
        user_id = input("Enter user ID (小米数字ID): ").strip()
    if not password:
        password = input("Enter password: ").strip()
    if not did:
        did = input("Enter device ID (did) [optional]: ").strip() or None

    print()
    print(f"Testing login with:")
    print(f"- userId: {user_id}")
    print(f"- password: {'*' * len(password)}")
    print(f"- did: {did}")
    print()

    # Perform login
    auth = XiaomiAuth()
    account = auth.login(
        user_id=user_id,
        password=password,
        did=did,
    )

    if not account:
        print()
        print("❌ Login failed!")
        return False

    print()
    print("✅ Login successful!")
    print()
    print("Account details:")
    print(f"- deviceId: {account.get('deviceId')}")
    print(f"- userId: {account.get('userId')}")
    print(f"- sid: {account.get('sid')}")
    print(f"- serviceToken: {account.get('serviceToken')[:50]}..." if account.get('serviceToken') else "- serviceToken: None")
    print()
    print("Pass details:")
    pass_info = account.get("pass", {})
    print(f"- code: {pass_info.get('code')}")
    print(f"- ssecurity: {pass_info.get('ssecurity')}")
    print(f"- nonce: {pass_info.get('nonce')}")
    print(f"- location: {pass_info.get('location')[:80]}..." if pass_info.get('location') else "- location: None")

    # Save to temp file for testing
    test_output = "/tmp/test_mi.json"
    if save_credentials(account, test_output):
        print()
        print(f"✅ Credentials saved to {test_output}")

    return True


if __name__ == "__main__":
    success = test_login()
    sys.exit(0 if success else 1)
