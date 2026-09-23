from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .inventory_activity.api import router
from .auth_api import router as auth_router
from .mcp_server import create_mcp
from .security import ProjectAuthMiddleware, admin_token, allowed_origins

def create_app() -> FastAPI:
    mcp, mcp_app = create_mcp()

    @asynccontextmanager
    async def lifespan(app):
        admin_token()  # Bootstrap on the server, never through an unauthenticated endpoint.
        async with mcp.session_manager.run():
            yield

    application = FastAPI(title="物料活跃度 MVP API", version="0.2.0", lifespan=lifespan)
    application.add_middleware(ProjectAuthMiddleware)
    application.add_middleware(CORSMiddleware, allow_origins=allowed_origins(),
                               allow_credentials=True, allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
                               allow_headers=["Authorization", "Content-Type", "MCP-Protocol-Version", "Mcp-Method", "Mcp-Name"])
    application.include_router(auth_router)
    application.include_router(router)

    @application.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # Define regular routes before the SDK's /mcp ASGI route.
    application.mount("/", mcp_app)
    return application


app = create_app()
