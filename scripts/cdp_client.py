"""Minimal client for the Coinbase CDP SQL API.

Auth: a short-lived JWT signed with the CDP secret API key (Ed25519 or EC).
Credentials come from the environment variables CDP_API_KEY_ID and CDP_API_KEY_SECRET
(set as GitHub Actions secrets - never commit them).
"""
import base64
import os
import re
import secrets
import time

import requests

API_HOST = "api.cdp.coinbase.com"
QUERY_PATH = "/platform/v2/data/query/run"


def _jwt_via_sdk(key_id: str, key_secret: str, method: str, host: str, path: str) -> str:
    # Preferred: the official CDP SDK's helper (handles Ed25519 and EC keys).
    from cdp.auth.utils.jwt import JwtOptions, generate_jwt

    return generate_jwt(
        JwtOptions(
            api_key_id=key_id,
            api_key_secret=key_secret,
            request_method=method,
            request_host=host,
            request_path=path,
            expires_in=120,
        )
    )


def _jwt_manual(key_id: str, key_secret: str, method: str, host: str, path: str) -> str:
    # Fallback for Ed25519 keys (base64 of 64 bytes: 32-byte seed + 32-byte public key).
    import jwt  # PyJWT
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    raw = base64.b64decode(key_secret)
    private_key = Ed25519PrivateKey.from_private_bytes(raw[:32])
    now = int(time.time())
    payload = {
        "sub": key_id,
        "iss": "cdp",
        "nbf": now,
        "exp": now + 120,
        "uris": [f"{method} {host}{path}"],
    }
    headers = {"kid": key_id, "nonce": secrets.token_hex(16), "typ": "JWT"}
    return jwt.encode(payload, private_key, algorithm="EdDSA", headers=headers)


def make_jwt(method: str = "POST", host: str = API_HOST, path: str = QUERY_PATH) -> str:
    key_id = os.environ["CDP_API_KEY_ID"].strip()
    key_secret = os.environ["CDP_API_KEY_SECRET"].strip()
    try:
        return _jwt_via_sdk(key_id, key_secret, method, host, path)
    except Exception as exc:  # SDK missing or its API changed -> sign ourselves
        print(f"[info] CDP SDK JWT unavailable ({type(exc).__name__}); using built-in signer")
        return _jwt_manual(key_id, key_secret, method, host, path)


def clean_sql(sql: str) -> str:
    """Strip -- comments and collapse whitespace (CDP max query length is 10,000 chars)."""
    sql = re.sub(r"--[^\n]*", "", sql)
    return re.sub(r"\s+", " ", sql).strip()


_CAMEL = re.compile(r"(?<!^)(?=[A-Z])")


def _normalise(value):
    # CDP quotes 64-bit numbers as strings; turn numeric strings into numbers,
    # but leave addresses/hashes (0x...) and dates alone.
    if isinstance(value, str) and not value.startswith("0x"):
        try:
            number = float(value)
            return int(number) if number.is_integer() and abs(number) < 2**53 else number
        except ValueError:
            return value
    return value


def run_query(sql: str, retries: int = 3) -> list[dict]:
    """Run one SQL query and return the rows as a list of dicts with snake_case keys."""
    body = {"sql": clean_sql(sql)}
    last_error = None
    for attempt in range(1, retries + 1):
        token = make_jwt()
        resp = requests.post(
            f"https://{API_HOST}{QUERY_PATH}",
            json=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=60,
        )
        if resp.status_code == 200:
            rows = resp.json().get("result") or []   # CDP returns null for an empty result
            return [
                {_CAMEL.sub("_", k).lower(): _normalise(v) for k, v in row.items()} for row in rows
            ]
        last_error = f"HTTP {resp.status_code}: {resp.text[:500]}"
        # Retry only on rate limits / server errors.
        if resp.status_code not in (429, 500, 502, 503, 504):
            break
        time.sleep(5 * attempt)
    raise RuntimeError(f"CDP query failed: {last_error}")
