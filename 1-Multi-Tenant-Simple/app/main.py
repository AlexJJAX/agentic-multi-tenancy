"""
FastAPI application entrypoint.

Configures the app, mounts routes, static files, and templates.
Handles startup lifecycle including database init, seeding, and indexing.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.tenants import router as tenants_router
from app.config import settings
from app.db import init_db
from app.rag.vector_store import index_all_tenants
from app.seed import run_all_seeds
from app.services.tenants import list_tenants

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Paths for templates and static files
APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"


def _static_asset_version(filename: str) -> int:
    """Return a cache-busting version derived from a static asset's modification time."""
    return (STATIC_DIR / filename).stat().st_mtime_ns


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.

    On startup:
    1. Load settings
    2. Ensure data directories exist
    3. Initialize SQLite database
    4. Seed tenants and KB files
    5. Initialize ChromaDB and index tenant documents
    6. Log index summary

    On shutdown:
    - Cleanup resources (if needed)
    """
    logger.info("=" * 60)
    logger.info("Starting Multi-Tenant RAG Chatbot")
    logger.info("=" * 60)

    # Step 1: Require live OpenAI credentials before mutating local state.
    settings.require_openai_api_key()

    # Log configuration (without secrets)
    logger.info("Chat model: %s", settings.chat_model)
    logger.info("Embedding model: %s", settings.embedding_model)
    logger.info("ChromaDB mode: %s", settings.chroma_mode)
    logger.info("SQLite path: %s", settings.sqlite_path)
    logger.info("KB root: %s", settings.kb_root)

    # Step 2: Ensure data directories exist
    settings.kb_root_path.mkdir(parents=True, exist_ok=True)
    logger.info("Data directories ready")

    # Step 3: Initialize SQLite
    await init_db()
    logger.info("SQLite database initialized")

    # Step 4: Seed tenants and KB files
    await run_all_seeds()
    logger.info("Seed operations complete")

    # Step 5: Index tenant documents into ChromaDB
    tenants = await list_tenants()
    tenant_ids = [t.tenant_id for t in tenants]

    if tenant_ids:
        results = await index_all_tenants(tenant_ids)

        # Step 6: Log index summary
        for result in results:
            logger.info(
                "Indexed tenant %s: %d documents, %d chunks",
                result["tenant_id"],
                result["documents"],
                result["chunks"],
            )
    else:
        logger.warning("No tenants found to index")

    logger.info("=" * 60)
    logger.info("Application ready at http://%s:%s", settings.app_host, settings.app_port)
    logger.info("=" * 60)

    yield  # Application is running

    logger.info("Shutting down Multi-Tenant RAG Chatbot")


# Create FastAPI app
app = FastAPI(
    title="Multi-Tenant RAG Chatbot",
    description="Local demo multi-tenant RAG chatbot with tenant-isolated knowledge bases",
    version="0.1.0",
    lifespan=lifespan,
)

# Mount static files
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Configure Jinja2 templates
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Include API routers
app.include_router(tenants_router)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(admin_router)


@app.get("/", response_class=HTMLResponse)
async def serve_ui(request: Request):
    """
    Serve the local web UI.

    Renders the index.html template with the application context.
    """
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "title": "Multi-Tenant RAG Chatbot",
            "styles_version": _static_asset_version("styles.css"),
            "app_version": _static_asset_version("app.js"),
        },
    )
