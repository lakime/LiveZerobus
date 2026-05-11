"""Bearer token auth + HMAC-signed file tokens for Delta Sharing."""
from __future__ import annotations

import hashlib
import hmac
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from typing import Optional

from fastapi import HTTPException, Request


def verify_bearer(request: Request, token: str) -> None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    if not hmac.compare_digest(auth[7:], token):
        raise HTTPException(status_code=403, detail="Invalid token")


def sign_file_token(secret: str, table: str, filename: str, ttl_s: int = 3600) -> str:
    expiry = int(time.time()) + ttl_s
    payload = f"{table}|{filename}|{expiry}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    raw = f"{payload}|{sig}"
    return urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def verify_file_token(secret: str, token: str, table: str, filename: str) -> Optional[str]:
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = urlsafe_b64decode(padded).decode()
        parts = raw.split("|")
        if len(parts) != 4:
            return None
        t_table, t_file, t_expiry, t_sig = parts
        if t_table != table or t_file != filename:
            return None
        if int(t_expiry) < time.time():
            return None
        expected = f"{t_table}|{t_file}|{t_expiry}"
        expected_sig = hmac.new(secret.encode(), expected.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(t_sig, expected_sig):
            return None
        return filename
    except Exception:
        return None
