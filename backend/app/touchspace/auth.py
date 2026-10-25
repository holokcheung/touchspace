"""Demo pairing: expiring credentials, installation-bound identity, no embedded secret."""
import base64
import hmac
import json
import os
import secrets
import time
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException


@lru_cache
def signing_secret():
    configured = os.environ.get("TOUCHSPACE_AUTH_SECRET")
    if configured:
        if len(configured) < 32:
            raise RuntimeError("TOUCHSPACE_AUTH_SECRET must contain at least 32 characters")
        return configured.encode()
    repo = Path(__file__).resolve().parents[3]
    root = Path(os.environ.get("TOUCHSPACE_DATA_DIR", repo / "backend" / "data"))
    root = (root if root.is_absolute() else repo / root) / "touchspace"
    root.mkdir(parents=True,exist_ok=True)
    path = root / ".auth-secret"
    try:
        descriptor = os.open(path,os.O_CREAT | os.O_EXCL | os.O_WRONLY,0o600)
        with os.fdopen(descriptor,"wb") as output:
            output.write(secrets.token_bytes(32))
    except FileExistsError:
        pass
    raw = path.read_bytes()
    if len(raw) < 32:
        raise RuntimeError("Invalid catalog signing secret")
    return raw


def encode(raw: bytes):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def issue(code: str, installation_id: str):
    expected = os.environ.get("TOUCHSPACE_PUBLISH_CODE")
    if not expected:
        raise HTTPException(503, "Publishing is disabled; configure a demo pairing code on the server")
    if not hmac.compare_digest(code.encode(), expected.encode()):
        raise HTTPException(401, "Invalid pairing code")
    secret = signing_secret()
    expires = int(time.time()) + 3600
    payload = encode(json.dumps({"sub": encode(hmac.digest(secret,installation_id.encode(),"sha256")), "exp": expires}).encode())
    signature = encode(hmac.digest(secret,payload.encode(),"sha256"))
    return {"token": payload + "." + signature, "expiresAt": expires}


def owner(authorization: str | None):
    if authorization is None:
        return None
    try:
        if not authorization.startswith("Bearer ") or len(authorization) > 1000:
            raise ValueError()
        payload, signature = authorization[7:].split(".")
        expected = encode(hmac.digest(signing_secret(),payload.encode(),"sha256"))
        if not hmac.compare_digest(signature,expected):
            raise ValueError()
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if data["exp"] <= time.time() or not isinstance(data["sub"],str):
            raise ValueError()
        return data["sub"]
    except (ValueError,KeyError,TypeError):
        raise HTTPException(401,"Publishing credential expired or invalid") from None
