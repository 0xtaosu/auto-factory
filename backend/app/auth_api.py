from datetime import datetime
import os

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from . import security

router = APIRouter()


class LoginInput(BaseModel):
    token: str = Field(min_length=1, max_length=512)


class KeyInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scopes: list[str] = Field(default_factory=lambda: ["activity:read"])
    expires_at: datetime | None = None


@router.post("/api/auth/login")
def login(body: LoginInput, request: Request, response: Response):
    secret, expires_at = security.login(body.token, request.client.host if request.client else "unknown")
    response.set_cookie(security.COOKIE_NAME, secret, max_age=8 * 60 * 60, httponly=True,
                        secure=os.environ.get("INVENTORY_COOKIE_SECURE", "false").lower() == "true",
                        samesite="strict", path="/api")
    response.headers["Cache-Control"] = "no-store"
    return {"role": "admin", "expires_at": expires_at}


@router.get("/api/auth/session")
def session(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {k: request.state.principal[k] for k in ("role", "expires_at")}


@router.post("/api/auth/logout")
def logout(request: Request, response: Response):
    security.logout(request.cookies.get(security.COOKIE_NAME, ""))
    response.delete_cookie(security.COOKIE_NAME, path="/api", httponly=True, samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}


@router.get("/api/admin/keys")
def list_keys(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"items": security.list_keys()}


@router.post("/api/admin/keys", status_code=201)
def create_key(body: KeyInput, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return security.create_key(body.name, body.scopes, body.expires_at)


@router.delete("/api/admin/keys/{key_id}")
def revoke_key(key_id: str):
    security.revoke_key(key_id)
    return {"ok": True}


@router.get("/api/admin/mcp")
def mcp_info():
    from .mcp_server import TOOL_INFO
    return {"endpoint_path": "/mcp", "transport": "streamable-http", "auth": "bearer-api-key",
            "tools": TOOL_INFO, "scopes": [
                {"name": "activity:read", "description": "查询本项目任务、评估、指标、证据和导出结果"},
                {"name": "activity:analyze", "description": "通过 REST API 上传 ERP 并创建分析任务"}],
            "data_access": "所有 Key 均可访问本项目的数据，不提供按 Key 隔离的数据集。"}
