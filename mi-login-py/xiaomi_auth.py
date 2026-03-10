"""
Xiaomi authentication module.

Implements OAuth2 authentication flow for Xiaomi devices.
Based on mi-service-lite: https://github.com/yulei189/mi-service-lite
"""

import base64
import hashlib
import json
import re
import time
import uuid
from typing import Optional, Dict, Any
from urllib.parse import urlencode, urlparse, parse_qs

import requests


class XiaomiAuth:
    """Xiaomi account authentication."""

    USER_AGENT = "Dalvik/2.1.0 (Linux; U; Android 10; RMX2111 Build/QP1A.190711.020) APP/xiaomi.mico APPV/2004040 MK/Uk1YMjExMQ== PassportSDK/3.8.3 passport-ui/3.8.3"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept-Encoding": "gzip, deflate",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": self.USER_AGENT,
        })

    @staticmethod
    def md5(text: str) -> str:
        """Calculate MD5 hash of text, return uppercase hex."""
        return hashlib.md5(text.encode()).hexdigest().upper()

    @staticmethod
    def sha1(text: str) -> str:
        """Calculate SHA1 hash, return base64."""
        return base64.b64encode(hashlib.sha1(text.encode()).digest()).decode("utf-8")

    @staticmethod
    def generate_device_id() -> str:
        """Generate a random Android device ID."""
        return f"android_{uuid.uuid4()}"

    @staticmethod
    def from_env() -> Optional[Dict[str, Any]]:
        """Read credentials from environment variables.

        Environment variables:
            XIAOMI_USER_ID: Xiaomi account ID (not phone number)
            XIAOMI_PASSWORD: Account password
            XIAOMI_DID: Device ID (optional)

        Returns:
            Dict with user_id, password, and did keys, or None if not set
        """
        import os

        user_id = os.environ.get("XIAOMI_USER_ID")
        password = os.environ.get("XIAOMI_PASSWORD")
        did = os.environ.get("XIAOMI_DID")

        if not user_id or not password:
            return None

        return {
            "user_id": user_id,
            "password": password,
            "did": did,
        }

    @staticmethod
    def parse_auth_pass(text: str) -> Dict[str, Any]:
        """
        Parse the authentication response from Xiaomi.

        The response comes as JavaScript-like format that needs conversion.
        """
        # Remove the &&&START&&& prefix
        text = text.replace("&&&START&&&", "")

        # Convert userId and nonce from numbers to strings
        # Pattern: :123456789 -> :"123456789"
        text = re.sub(r':(\d{9,})', r':"\1"', text)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}

    def login(self, user_id: str, password: str | None = None, did: str = None, sid: str = "micoapi") -> Optional[Dict[str, Any]]:
        """
        Perform OAuth2 authentication with Xiaomi account.

        Args:
            user_id: Xiaomi account ID (not phone number)
            password: Account password (optional, will read from XIAOMI_PASSWORD env if not provided)
            did: Device ID (optional)
            sid: Service ID (default: micoapi)

        Returns:
            Account dictionary with credentials, or None on failure
        """
        # If password not provided, try to read from environment
        if not password:
            env_creds = self.from_env()
            if env_creds:
                user_id = env_creds.get("user_id", user_id)
                password = env_creds.get("password")
                did = did or env_creds.get("did")

        if not password:
            print("Error: Password not provided and XIAOMI_PASSWORD env not set")
            return None
        device_id = did or self.generate_device_id()

        # Step 1: Get initial login page to get auth parameters
        print("Step 1: Getting initial auth parameters...")
        pass_info = self._get_auth_params(sid)
        if not pass_info:
            print("Failed to get initial auth parameters")
            return None

        # Check if already authenticated (code=0)
        if pass_info.get("code") == 0:
            print("Already authenticated, getting service token...")
        else:
            # Step 2: Submit credentials
            print("Step 2: Submitting credentials...")
            pass_info = self._submit_credentials(pass_info, user_id, password, sid)
            if not pass_info:
                print("Failed to submit credentials")
                return None

        # Check for security verification
        if not pass_info.get("location") or not pass_info.get("nonce") or not pass_info.get("passToken"):
            if pass_info.get("notificationUrl") or pass_info.get("captchaUrl"):
                print("\nSecurity verification required!")
                print("Please open the following link in your browser and authorize:")
                print(pass_info.get("notificationUrl") or pass_info.get("captchaUrl"))
                print("\nNote: After authorization, please wait about 1 hour before retrying.")
            print("Login failed: missing required parameters")
            return None

        # Step 3: Get service token
        print("Step 3: Getting service token...")
        service_token = self._get_service_token(pass_info)
        if not service_token:
            print("Failed to get service token")
            return None

        print("Login successful!")

        # Build account object
        account = {
            "deviceId": device_id,
            "did": did,
            "userId": user_id,
            "password": password,
            "sid": sid,
            "pass": pass_info,
            "serviceToken": service_token,
        }

        # Step 4: Get device info
        if did:
            print("Step 4: Getting device info...")
            device_info = self.get_device_info(account)
            if device_info:
                account["device"] = device_info
                account["did"] = device_info.get("miotDID") or did
            else:
                print("Warning: Could not fetch device info")

        return account

    def _get_auth_params(self, sid: str) -> Optional[Dict[str, Any]]:
        """Step 1: Get initial authentication parameters."""
        url = "https://account.xiaomi.com/pass/serviceLogin"
        params = {
            "sid": sid,
            "_json": "true",
            "_locale": "zh_CN",
        }

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return self.parse_auth_pass(response.text)
        except Exception as e:
            print(f"Error getting auth params: {e}")
            return None

    def _submit_credentials(self, pass_info: Dict[str, Any], user_id: str, password: str, sid: str) -> Optional[Dict[str, Any]]:
        """Step 2: Submit user credentials."""
        url = "https://account.xiaomi.com/pass/serviceLoginAuth2"

        # Calculate password hash
        password_hash = self.md5(password)

        data = {
            "_json": "true",
            "qs": pass_info.get("qs", ""),
            "sid": sid,
            "_sign": pass_info.get("_sign", ""),
            "callback": pass_info.get("callback", ""),
            "user": user_id,
            "hash": password_hash,
        }

        try:
            response = self.session.post(url, data=data, timeout=10)
            response.raise_for_status()
            return self.parse_auth_pass(response.text)
        except Exception as e:
            print(f"Error submitting credentials: {e}")
            return None

    def _get_service_token(self, pass_info: Dict[str, Any]) -> Optional[str]:
        """Step 3: Get service token from location URL."""
        location = pass_info.get("location")
        nonce = pass_info.get("nonce")
        ssecurity = pass_info.get("ssecurity")

        if not all([location, nonce, ssecurity]):
            return None

        # Calculate clientSign
        client_sign = self.sha1(f"nonce={nonce}&{ssecurity}")

        params = {
            "_userIdNeedEncrypt": "true",
            "clientSign": client_sign,
        }

        try:
            response = self.session.get(location, params=params, timeout=10, allow_redirects=False)

            # Extract serviceToken from cookies
            cookies = response.headers.get("set-cookie", "")
            for cookie in cookies.split(","):
                if "serviceToken" in cookie:
                    # Extract serviceToken value
                    token = cookie.split(";")[0].replace("serviceToken=", "")
                    return token

            print(f"Response headers: {response.headers}")
            print(f"Failed to extract serviceToken from cookies")
            return None
        except Exception as e:
            print(f"Error getting service token: {e}")
            return None

    def get_device_info(self, account: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Get device information for the specified device.

        Args:
            account: Account dictionary from login()

        Returns:
            Device information dictionary
        """
        if not account.get("serviceToken"):
            print("No service token available")
            return None

        print("Fetching device list...")
        url = "https://api2.mina.mi.com/admin/v2/device_list"
        params = {
            "requestId": str(uuid.uuid4()),
            "timestamp": int(time.time()),
        }

        headers = {
            "User-Agent": "MICO/AndroidApp/@SHIP.TO.2A2FE0D7@/2.4.40",
        }

        cookies = {
            "userId": account.get("userId"),
            "serviceToken": account.get("serviceToken"),
        }

        try:
            response = self.session.get(url, params=params, headers=headers, cookies=cookies, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 0:
                print(f"Failed to get device list: {data}")
                return None

            devices = data.get("data", [])
            did = account.get("did")

            # Find the device matching the did
            for device in devices:
                if device.get("deviceID") == did or device.get("miotDID") == did or device.get("name") == did:
                    device["deviceId"] = device["deviceID"]
                    return device

            # If no match found but we have devices, return the first one
            if devices:
                device = devices[0]
                device["deviceId"] = device["deviceID"]
                return device

            print("No devices found")
            return None
        except Exception as e:
            print(f"Error getting device info: {e}")
            return None


def save_credentials(account: Dict[str, Any], filepath: str = ".mi.json") -> bool:
    """
    Save credentials to JSON file.

    Args:
        account: Account dictionary
        filepath: Output file path

    Returns:
        True if successful
    """
    try:
        # Load existing file to preserve other services
        try:
            with open(filepath, "r") as f:
                store = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            store = {}

        # Save as mina service (same as mi-service-lite)
        store["mina"] = account

        with open(filepath, "w") as f:
            json.dump(store, f, indent=2, ensure_ascii=False)

        print(f"Credentials saved to {filepath}")
        return True
    except Exception as e:
        print(f"Error saving credentials: {e}")
        return False
