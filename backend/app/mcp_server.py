"""Read-only MCP tools over the existing inventory activity service."""
from __future__ import annotations

import json
import os
from typing import Annotated, Literal, Any

from fastapi import HTTPException
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field

from .inventory_activity import api
from .security import allowed_origins

TOOL_INFO = [
    {"name": "list_jobs", "description": "分页列出本项目分析任务"},
    {"name": "get_job", "description": "读取任务状态与数据质量概览"},
    {"name": "get_overview", "description": "读取指标分布、候选数量、策略和观察边界"},
    {"name": "list_assessments", "description": "搜索或筛选物料评估，支持分页"},
    {"name": "explain_material", "description": "追溯物料判断、指标、末次事件及 ERP 原始行"},
    {"name": "get_export_info", "description": "获取导出文件元数据与需要同一 Key 鉴权的下载路径"},
]


def service_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except HTTPException as exc:
        raise ValueError(f"{exc.status_code}: {exc.detail}") from None


def create_mcp():
    server = MCPServer("Inventory Activity", version="0.1.0",
                       instructions="Query this project's ERP activity facts. Inactive candidates do not prove current stock. Honor data windows and null metrics; never infer inventory balances.")
    annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

    @server.tool(annotations=annotations, structured_output=True)
    def list_jobs(offset: Annotated[int, Field(ge=0)] = 0,
                  limit: Annotated[int, Field(ge=1, le=100)] = 20) -> dict[str, Any]:
        """List project analysis jobs, newest first. Use returned job_id in other tools."""
        with api.database() as conn:
            total = conn.execute("SELECT count(*) FROM activity_jobs").fetchone()[0]
            rows = conn.execute("SELECT metadata FROM activity_jobs ORDER BY rowid DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return {"total": total, "items": [json.loads(row["metadata"]) for row in rows]}

    @server.tool(annotations=annotations, structured_output=True)
    def get_job(job_id: str) -> dict[str, Any]:
        """Read a job's status, source filename and data quality. Failed jobs have no usable assessment."""
        return service_call(api.get_job, job_id)

    @server.tool(annotations=annotations, structured_output=True)
    def get_overview(job_id: str) -> dict[str, Any]:
        """Read counts, recency statistics, policy snapshot, data coverage and observation limitations."""
        return service_call(api.get_overview, job_id)

    @server.tool(annotations=annotations, structured_output=True)
    def list_assessments(job_id: str, q: str = "", inactive_only: bool = False,
                         offset: Annotated[int, Field(ge=0)] = 0,
                         limit: Annotated[int, Field(ge=1, le=100)] = 20) -> dict[str, Any]:
        """Search material code/name and filter inactivity candidates. Null quantities are not zero; preserve per-unit quantities."""
        return service_call(api.get_assessments, job_id, q, inactive_only, offset, limit)

    @server.tool(annotations=annotations, structured_output=True)
    def explain_material(job_id: str, material_code: str) -> dict[str, Any]:
        """Explain why a material is or is not a candidate, including policy, metrics, last events and original ERP rows."""
        return service_call(api.get_explanation, job_id, material_code)

    @server.tool(annotations=annotations, structured_output=True)
    def get_export_info(job_id: str, format: Literal["json", "csv", "ttl", "report"] = "json") -> dict[str, Any]:
        """Return file metadata and authenticated REST download path. Send the same Bearer key in a header; do not put keys in URLs. Large exports are not inlined."""
        directory = service_call(api.completed_dir, job_id)
        name, content_type = api.EXPORTS[format]
        return {"filename": name, "media_type": content_type, "size_bytes": (directory / name).stat().st_size,
                "download_path": f"/api/activity/jobs/{job_id}/download/{format}",
                "authentication": "Authorization: Bearer <API_KEY>"}

    security = TransportSecuritySettings(
        allowed_hosts=[v.strip() for v in os.environ.get("INVENTORY_ALLOWED_HOSTS", "localhost:*,127.0.0.1:*,[::1]:*").split(",") if v.strip()],
        allowed_origins=allowed_origins(),
    )
    http_app = server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True,
                                          json_response=True, transport_security=security)
    return server, http_app
