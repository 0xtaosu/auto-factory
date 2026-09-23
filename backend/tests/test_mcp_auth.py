from datetime import timedelta
import json
import stat

import pytest
from fastapi.testclient import TestClient

from app import security
from app.inventory_activity import api
from app.main import create_app
from test_activity_api import TEST_ADMIN_TOKEN, login
from test_inventory_activity import row, workbook


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DATA_ROOT", tmp_path)
    monkeypatch.setenv("INVENTORY_ADMIN_TOKEN", TEST_ADMIN_TOKEN)
    monkeypatch.delenv("INVENTORY_AUTH_DIR", raising=False)
    with TestClient(create_app(), base_url="http://localhost:8000") as client:
        yield client


def issue(client, **changes):
    response = client.post("/api/admin/keys", json={"name": "Test Agent", "scopes": ["activity:read"], **changes})
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def bearer(issued):
    return {"Authorization": "Bearer " + issued["key"]}


def test_unauthenticated_routes_and_admin_login(client):
    assert client.get("/api/health").status_code == 200
    for path in ("/api/activity/config", "/api/activity/jobs/abc/overview", "/api/activity/jobs/abc/download/json",
                 "/api/admin/keys", "/api/auth/session", "/mcp"):
        response = client.get(path)
        assert response.status_code == 401, (path, response.text)
        assert response.headers["www-authenticate"].startswith("Bearer")
    assert client.post("/api/admin/keys", json={"name": "bad"}).status_code == 401
    assert client.post("/api/auth/login", json={"token": "bad"}).status_code == 401
    login(client)
    assert client.get("/api/auth/session").json()["role"] == "admin"
    assert client.get("/api/activity/config").status_code == 200
    assert client.get("/mcp").status_code == 401  # admin cookie is never an MCP credential
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/session").status_code == 401


def test_independent_keys_hash_storage_admin_scope_and_revoke(client):
    login(client)
    first, second = issue(client), issue(client, name="Second Agent")
    assert first["key"] != second["key"]
    assert first["info"]["key_id"] != second["info"]["key_id"]
    listing = client.get("/api/admin/keys")
    assert first["key"] not in listing.text and "token_hash" not in listing.text
    with security.connection() as conn:
        row = conn.execute("SELECT * FROM api_keys WHERE key_id=?", (first["info"]["key_id"],)).fetchone()
        assert row["token_hash"] == security.fingerprint(first["key"])
        assert first["key"] not in json.dumps(dict(row))
    headers = bearer(first)
    assert client.get("/api/activity/config", headers=headers).status_code == 200
    assert client.get("/api/admin/keys", headers=headers).status_code == 403
    assert client.post("/api/admin/keys", headers=headers, json={"name": "child"}).status_code == 403
    assert client.post("/api/activity/jobs", headers=headers).status_code == 403
    assert client.post("/api/auth/login", json={"token": first["key"]}).status_code == 401
    rows = client.get("/api/admin/keys").json()["items"]
    assert next(r for r in rows if r["key_id"] == first["info"]["key_id"])["last_used_at"]
    assert client.delete("/api/admin/keys/" + first["info"]["key_id"]).status_code == 200
    assert client.delete("/api/admin/keys/" + first["info"]["key_id"]).status_code == 200
    assert client.get("/api/activity/config", headers=headers).status_code == 401
    assert client.get("/api/activity/jobs/abc/download/json", headers=headers).status_code == 401
    assert client.get("/api/activity/config", headers=bearer(second)).status_code == 200


def test_expiry_validation_and_immediate_expiration(client):
    login(client)
    for body in ({"name": " "}, {"name": "x", "scopes": ["admin"]},
                 {"name": "x", "expires_at": "2020-01-01T00:00:00+00:00"},
                 {"name": "x", "expires_at": "2099-01-01T00:00:00"}):
        assert client.post("/api/admin/keys", json=body).status_code == 422
    key = issue(client, expires_at=(security.utcnow() + timedelta(hours=1)).isoformat())
    with security.connection() as conn:
        conn.execute("UPDATE api_keys SET expires_at=? WHERE key_id=?", ("2000-01-01T00:00:00+00:00", key["info"]["key_id"]))
    assert client.get("/api/activity/config", headers=bearer(key)).status_code == 401
    assert client.get("/api/admin/keys").json()["items"][0]["status"] == "expired"


def test_origin_and_header_credentials(client):
    login(client)
    key = issue(client)
    assert client.post("/api/admin/keys", json={"name": "evil"}, headers={"Origin": "https://evil.invalid"}).status_code == 403
    assert client.get("/mcp", headers={**bearer(key), "Origin": "https://evil.invalid"}).status_code == 403
    assert client.get("/api/activity/config", headers={"Authorization": "Basic x"}).status_code == 401
    assert client.get("/api/activity/config", headers={"Authorization": "Bearer bad"}).status_code == 401
    client.cookies.clear()
    assert client.get("/api/activity/config?api_key=" + key["key"]).status_code == 401
    assert client.post("/api/auth/login", json={"token": TEST_ADMIN_TOKEN}, headers={"Origin": "null"}).status_code == 403


def test_session_expiry_logout_and_admin_rotation(client, monkeypatch):
    login(client)
    cookie = client.cookies.get(security.COOKIE_NAME)
    with security.connection() as conn:
        conn.execute("UPDATE admin_sessions SET expires_at=?", ("2000-01-01T00:00:00+00:00",))
    assert client.get("/api/auth/session").status_code == 401
    login(client)
    monkeypatch.setenv("INVENTORY_ADMIN_TOKEN", TEST_ADMIN_TOKEN + "rotated")
    assert client.get("/api/auth/session").status_code == 401
    assert cookie


def test_login_rate_limit(client):
    for _ in range(10):
        assert client.post("/api/auth/login", json={"token": "incorrect"}).status_code == 401
    assert client.post("/api/auth/login", json={"token": "incorrect"}).status_code == 429


def test_local_admin_bootstrap(tmp_path, monkeypatch):
    monkeypatch.delenv("INVENTORY_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("INVENTORY_AUTH_DIR", str(tmp_path))
    token = security.admin_token()
    assert token == security.admin_token() and len(token) > 40
    assert stat.S_IMODE((tmp_path / "admin-token").stat().st_mode) == 0o600


def rpc(client, key, method, params=None, request_id=1):
    headers = {**bearer(key), "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}
    return client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})


def test_mcp_initialize_tools_read_provenance_and_revocation(client):
    login(client)
    key = issue(client)
    job = client.post("/api/activity/jobs", files={"file": ("mcp-test.xlsx", workbook(row("GC010", 180)))}).json()
    assert job["status"] == "completed"
    initialized = rpc(client, key, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "pytest", "version": "1"}})
    assert initialized.status_code == 200, initialized.text
    assert initialized.json()["result"]["serverInfo"]["name"] == "Inventory Activity"
    listed = rpc(client, key, "tools/list")
    assert listed.status_code == 200, listed.text
    names = {t["name"] for t in listed.json()["result"]["tools"]}
    assert names == {"list_jobs", "get_job", "get_overview", "list_assessments", "explain_material", "get_export_info"}
    for name, args in [
        ("list_jobs", {}), ("get_job", {"job_id": job["job_id"]}),
        ("get_overview", {"job_id": job["job_id"]}),
        ("list_assessments", {"job_id": job["job_id"], "inactive_only": True}),
        ("explain_material", {"job_id": job["job_id"], "material_code": "GC010"}),
        ("get_export_info", {"job_id": job["job_id"], "format": "ttl"}),
    ]:
        response = rpc(client, key, "tools/call", {"name": name, "arguments": args})
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert not result.get("isError"), result
        content = result["structuredContent"]
        if name == "explain_material":
            assert content["assessment"]["days_since_last_movement"] == 180
            assert content["source_records"][0]["excel_row"] == 2
        if name == "get_export_info":
            assert client.get(content["download_path"], headers=bearer(key)).status_code == 200
            assert key["key"] not in json.dumps(content)
    invalid = rpc(client, key, "tools/call", {"name": "list_assessments", "arguments": {"job_id": job["job_id"], "limit": 1000}})
    assert invalid.json()["result"]["isError"]
    client.delete("/api/admin/keys/" + key["info"]["key_id"])
    assert rpc(client, key, "tools/list").status_code == 401


def test_analyze_scope_allows_upload_without_admin_privileges(client):
    login(client)
    key = issue(client, scopes=["activity:read", "activity:analyze"])
    client.cookies.clear()
    response = client.post("/api/activity/jobs", headers=bearer(key), files={"file": ("test.xlsx", workbook(row()))})
    assert response.json()["status"] == "completed"
    assert client.get("/api/admin/keys", headers=bearer(key)).status_code == 403


def test_official_sdk_client_current_protocol(tmp_path, monkeypatch):
    import asyncio
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    monkeypatch.setattr(api, "DATA_ROOT", tmp_path)
    monkeypatch.setenv("INVENTORY_ADMIN_TOKEN", TEST_ADMIN_TOKEN)
    monkeypatch.delenv("INVENTORY_AUTH_DIR", raising=False)
    key = security.create_key("SDK client", ["activity:read"], None)
    application = create_app()

    async def exercise():
        async with application.router.lifespan_context(application):
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(application), headers=bearer(key)) as http:
                transport = streamable_http_client("http://localhost:8000/mcp", http_client=http)
                async with Client(transport) as mcp:
                    tools = await mcp.list_tools()
                    assert len(tools.tools) == 6
                    result = await mcp.call_tool("list_jobs", {"limit": 10})
                    assert not result.is_error
                    assert result.structured_content == {"total": 0, "items": []}

    asyncio.run(exercise())
