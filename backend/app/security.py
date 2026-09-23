"""Project credentials: independent API keys and administrator browser sessions."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

COOKIE_NAME = "inventory_admin_session"
SCOPES = {"activity:read", "activity:analyze"}
DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def fingerprint(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def auth_dir() -> Path:
    from .inventory_activity import api
    return Path(os.environ.get("INVENTORY_AUTH_DIR", str(api.DATA_ROOT / "auth")))


def admin_token() -> str:
    configured = os.environ.get("INVENTORY_ADMIN_TOKEN", "")
    if configured:
        if len(configured) < 32:
            raise RuntimeError("INVENTORY_ADMIN_TOKEN must have at least 32 characters")
        return configured
    directory = auth_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / "admin-token"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "w") as handle:
            handle.write("ia_admin_" + secrets.token_urlsafe(32))
    token = path.read_text().strip()
    if len(token) < 32:
        raise RuntimeError("Invalid administrator token file")
    return token


@contextmanager
def connection():
    directory = auth_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    conn = sqlite3.connect(directory / "credentials.sqlite3", timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS api_keys (
              key_id TEXT PRIMARY KEY, name TEXT NOT NULL, prefix TEXT NOT NULL,
              token_hash TEXT UNIQUE NOT NULL, scopes TEXT NOT NULL,
              created_at TEXT NOT NULL, expires_at TEXT, last_used_at TEXT, revoked_at TEXT);
            CREATE TABLE IF NOT EXISTS admin_sessions (
              token_hash TEXT PRIMARY KEY, admin_fingerprint TEXT NOT NULL,
              created_at TEXT NOT NULL, expires_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS login_failures (client TEXT NOT NULL, attempted_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS login_failures_client ON login_failures(client, attempted_at);
        """)
        yield conn
        conn.commit()
    finally:
        conn.close()


def key_info(row) -> dict:
    item = {k: row[k] for k in ("key_id", "name", "prefix", "created_at", "expires_at", "last_used_at", "revoked_at")}
    item["scopes"] = json.loads(row["scopes"])
    item["status"] = ("revoked" if item["revoked_at"] else
                      "expired" if item["expires_at"] and item["expires_at"] <= utcnow().isoformat() else "active")
    return item


def create_key(name: str, scopes: list[str], expires_at: datetime | None) -> dict:
    name = name.strip()
    if not 1 <= len(name) <= 80:
        raise HTTPException(422, "Key 名称需要 1～80 个字符")
    if not scopes or not set(scopes) <= SCOPES or "activity:read" not in scopes:
        raise HTTPException(422, "必须包含 activity:read，且只支持 activity:read / activity:analyze")
    if expires_at is not None:
        if expires_at.tzinfo is None:
            raise HTTPException(422, "有效期必须包含时区")
        expires_at = expires_at.astimezone(timezone.utc)
        if expires_at <= utcnow():
            raise HTTPException(422, "有效期必须晚于当前时间")
    key = "ia_key_" + secrets.token_urlsafe(32)
    key_id = uuid4().hex
    with connection() as conn:
        conn.execute("INSERT INTO api_keys VALUES (?,?,?,?,?,?,?,?,NULL)",
                     (key_id, name, key[:15], fingerprint(key), json.dumps(sorted(set(scopes))),
                      utcnow().isoformat(), expires_at.isoformat() if expires_at else None, None))
        info = key_info(conn.execute("SELECT * FROM api_keys WHERE key_id=?", (key_id,)).fetchone())
    return {"key": key, "info": info}


def list_keys() -> list[dict]:
    with connection() as conn:
        return [key_info(row) for row in conn.execute("SELECT * FROM api_keys ORDER BY created_at DESC, key_id")]


def revoke_key(key_id: str) -> None:
    with connection() as conn:
        result = conn.execute("UPDATE api_keys SET revoked_at=COALESCE(revoked_at,?) WHERE key_id=?", (utcnow().isoformat(), key_id))
        if result.rowcount == 0:
            raise HTTPException(404, "Key 不存在")


def authenticate_key(token: str) -> dict:
    now = utcnow().isoformat()
    with connection() as conn:
        row = conn.execute("SELECT * FROM api_keys WHERE token_hash=?", (fingerprint(token),)).fetchone()
        if row is None or row["revoked_at"] or (row["expires_at"] and row["expires_at"] <= now):
            raise HTTPException(401, "API Key 无效、已过期或已撤销")
        conn.execute("UPDATE api_keys SET last_used_at=? WHERE key_id=?", (now, row["key_id"]))
        return {"role": "api_key", "key_id": row["key_id"], "scopes": json.loads(row["scopes"])}


def login(token: str, client: str) -> tuple[str, str]:
    now = utcnow()
    cutoff = (now - timedelta(minutes=5)).isoformat()
    with connection() as conn:
        conn.execute("DELETE FROM login_failures WHERE attempted_at < ?", (cutoff,))
        count = conn.execute("SELECT count(*) FROM login_failures WHERE client=?", (client,)).fetchone()[0]
    if count >= 10:
        raise HTTPException(429, "登录尝试过多，请在 5 分钟后重试")
    if not hmac.compare_digest(fingerprint(token), fingerprint(admin_token())):
        with connection() as conn:
            conn.execute("INSERT INTO login_failures VALUES (?,?)", (client, now.isoformat()))
        raise HTTPException(401, "管理员凭据错误")
    secret = secrets.token_urlsafe(32)
    expires = (now + timedelta(hours=8)).isoformat()
    with connection() as conn:
        conn.execute("DELETE FROM admin_sessions WHERE expires_at <= ?", (now.isoformat(),))
        conn.execute("INSERT INTO admin_sessions VALUES (?,?,?,?)", (fingerprint(secret), fingerprint(admin_token()), now.isoformat(), expires))
        conn.execute("DELETE FROM login_failures WHERE client=?", (client,))
    return secret, expires


def authenticate_session(token: str) -> dict:
    with connection() as conn:
        row = conn.execute("SELECT * FROM admin_sessions WHERE token_hash=?", (fingerprint(token),)).fetchone()
    if row is None or row["expires_at"] <= utcnow().isoformat() or not hmac.compare_digest(row["admin_fingerprint"], fingerprint(admin_token())):
        raise HTTPException(401, "管理员会话已失效，请重新登录")
    return {"role": "admin", "scopes": sorted(SCOPES), "expires_at": row["expires_at"]}


def logout(token: str) -> None:
    with connection() as conn:
        conn.execute("DELETE FROM admin_sessions WHERE token_hash=?", (fingerprint(token),))


def allowed_origins() -> list[str]:
    return [x.strip().rstrip("/") for x in os.environ.get("INVENTORY_ALLOWED_ORIGINS", DEFAULT_ORIGINS).split(",") if x.strip()]


class ProjectAuthMiddleware:
    """Pure ASGI middleware also protects streaming MCP, before any tool is run."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        path = request.url.path
        protected = path.startswith(("/api/activity", "/api/admin", "/api/auth", "/mcp"))
        if not protected or request.method == "OPTIONS":
            return await self.app(scope, receive, send)
        try:
            origin = request.headers.get("origin")
            if origin is not None and origin.rstrip("/") not in allowed_origins():
                raise HTTPException(403, "请求来源未授权")
            if path == "/api/auth/login":
                return await self.app(scope, receive, send)
            header = request.headers.get("authorization")
            if header:
                scheme, _, token = header.partition(" ")
                if scheme.lower() != "bearer" or not token or len(token) > 512:
                    raise HTTPException(401, "需要有效的 Bearer API Key")
                principal = await run_in_threadpool(authenticate_key, token)
            elif path.startswith("/mcp"):
                raise HTTPException(401, "MCP 需要 Authorization: Bearer <API_KEY>")
            else:
                token = request.cookies.get(COOKIE_NAME)
                if not token:
                    raise HTTPException(401, "请登录或提供 API Key")
                principal = await run_in_threadpool(authenticate_session, token)
                if request.method not in {"GET", "HEAD"} and origin is None:
                    raise HTTPException(403, "浏览器写入请求必须提供受信任的 Origin")
            if path.startswith(("/api/admin", "/api/auth")) and principal["role"] != "admin":
                raise HTTPException(403, "此操作仅限管理员会话")
            needed = "activity:analyze" if path.rstrip("/") == "/api/activity/jobs" and request.method == "POST" else "activity:read"
            if needed not in principal["scopes"]:
                raise HTTPException(403, "Key 缺少权限: " + needed)
            scope.setdefault("state", {})["principal"] = principal
        except HTTPException as exc:
            headers = {"Cache-Control": "no-store"}
            if exc.status_code == 401:
                headers["WWW-Authenticate"] = 'Bearer realm="inventory-activity"'
            response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=headers)
            return await response(scope, receive, send)
        await self.app(scope, receive, send)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="本机管理员凭据管理，不通过 API 暴露凭据")
    parser.add_argument("command", choices=["show-admin-token"])
    parser.parse_args()
    print(admin_token())
