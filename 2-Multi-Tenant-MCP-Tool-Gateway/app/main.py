"""Single ASGI entrypoint for UI, identity, agent, gateway, TVM, and targets."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.agent.routes import router as agent_router
from app.auth.routes import router as auth_router
from app.gateway.mcp_app import gateway_asgi_app, gateway_mcp
from app.lifespan import RuntimeDependencies, build_runtime
from app.settings import Settings, settings
from app.shared.correlation import correlation_id
from app.targets.orders.routes import router as orders_router
from app.targets.properties.mcp_app import properties_asgi_app, properties_mcp
from app.tvm.routes import router as tvm_router

APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(APP_DIR / "web" / "templates"))


def create_app(
    app_settings: Settings | None = None,
    *,
    runtime_dependencies: RuntimeDependencies | None = None,
) -> FastAPI:
    """Create the one-process application, optionally with isolated test settings."""

    selected_settings = app_settings or settings

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        runtime = await build_runtime(selected_settings, runtime_dependencies)
        application.state.runtime = runtime
        async with contextlib.AsyncExitStack() as stack:
            await stack.enter_async_context(gateway_mcp.session_manager.run())
            await stack.enter_async_context(properties_mcp.session_manager.run())
            yield
        await runtime.close()

    application = FastAPI(
        title="Local Multi-Tenant MCP Tool Gateway",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if selected_settings.testing else None,
        redoc_url=None,
    )
    logging.basicConfig(
        level=getattr(logging, selected_settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    @application.middleware("http")
    async def request_correlation(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = correlation_id(request.headers.get("x-request-id"))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    application.include_router(auth_router)
    application.include_router(agent_router)
    application.include_router(orders_router)
    application.include_router(tvm_router)
    application.mount(
        "/mcp",
        gateway_asgi_app(lambda: application.state.runtime),
        name="mcp-gateway",
    )
    application.mount(
        "/internal/mcp/properties",
        properties_asgi_app(lambda: application.state.runtime),
        name="properties-mcp",
    )
    application.mount(
        "/static",
        StaticFiles(directory=str(APP_DIR / "web" / "static")),
        name="static",
    )

    @application.get("/health")
    async def health() -> dict[str, str]:
        """Return process liveness without exposing configuration."""

        return {"status": "ok"}

    @application.get("/ready")
    async def ready(request: Request) -> JSONResponse:
        """Report readiness only after all embedded components initialize."""

        runtime = getattr(request.app.state, "runtime", None)
        is_ready = bool(runtime and runtime.ready and runtime.store.health())
        payload = {
            "status": "ready" if is_ready else "not_ready",
            "checks": {
                "sqlite": bool(runtime and runtime.store.health()),
                "identity_keys": bool(runtime and runtime.identity_authority.kid),
                "orders_store": bool(runtime),
                "rag": bool(runtime and runtime.rag.ready()),
                "mcp_gateway": bool(runtime),
                "properties_mcp": bool(runtime),
            },
        }
        return JSONResponse(payload, status_code=200 if is_ready else 503)

    @application.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        """Serve the local cookie-authenticated chat workspace."""

        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"title": "Multi-Tenant MCP Tool Gateway"},
        )

    return application


app = create_app()
