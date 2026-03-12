#!/usr/bin/env python3
"""
Xiaomi Login Tool

Usage:
    python login.py --user-id USER_ID --password PASSWORD --did DID
    python login.py -u 2343839033 -p password -d 500410169
"""

import argparse
import sys

from xiaomi_auth import XiaomiAuth, save_credentials


def main():
    parser = argparse.ArgumentParser(description="Xiaomi Login Tool")
    parser.add_argument("-u", "--user-id", required=True, help="Xiaomi account ID (not phone number)")
    parser.add_argument("-p", "--password", required=True, help="Account password")
    parser.add_argument("-d", "--did", help="Device ID (optional)")
    parser.add_argument("-o", "--output", default=".mi.json", help="Output file path (default: .mi.json)")
    parser.add_argument("-s", "--sid", default="micoapi", help="Service ID (default: micoapi)")
    parser.add_argument("-r", "--retries", type=int, default=2, help="Max retries for security verification (default: 5)")
    parser.add_argument("-t", "--retry-delay", type=int, default=10, help="Delay in seconds between retries (default: 10)")

    args = parser.parse_args()

    print("=" * 40)
    print("Xiaomi Login Tool (Python)")
    print("=" * 40)
    print()
    print("Input parameters:")
    print(f"- userId: {args.user_id}")
    print(f"- password: {'*' * len(args.password)}")
    print(f"- did: {args.did or 'auto-generated'}")
    print(f"- sid: {args.sid}")
    print()

    # Check required parameters
    if not args.user_id or not args.password:
        parser.error("userId and password are required")

    # Perform login
    auth = XiaomiAuth()
    account = auth.login(
        user_id=args.user_id,
        password=args.password,
        did=args.did,
        sid=args.sid,
        max_retries=args.retries,
        retry_delay=args.retry_delay,
    )

    if not account:
        print()
        print("Login failed!")
        sys.exit(1)

    print()
    print(f"Login successful!")
    print(f"- userId: {account.get('userId')}")
    print(f"- serviceToken: {account.get('serviceToken')[:50]}..." if account.get('serviceToken') else "- serviceToken: None")
    print()

    # Save credentials
    if save_credentials(account, args.output):
        print()
        print("=" * 40)
        print("Login completed!")
        print("=" * 40)
    else:
        print("Failed to save credentials")
        sys.exit(1)


if __name__ == "__main__":
    main()
