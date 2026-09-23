"""Run: INVENTORY_API_KEY=... .venv/bin/python backend/mcp_client_example.py"""
import asyncio
import json
import os

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


async def main():
    key = os.environ["INVENTORY_API_KEY"]
    url = os.environ.get("INVENTORY_MCP_URL", "http://localhost:8000/mcp")
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {key}"},
                                 timeout=httpx2.Timeout(30, read=300)) as http:
        async with Client(streamable_http_client(url, http_client=http)) as client:
            tools = await client.list_tools()
            print("Tools:", ", ".join(tool.name for tool in tools.tools))
            result = await client.call_tool("list_jobs", {"limit": 10})
            print(json.dumps(result.structured_content, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
