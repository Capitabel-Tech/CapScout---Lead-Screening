import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import auth, customers, geo, meetings, meta
from app.zoho.worker import SyncWorker

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    cfg = get_settings()
    worker = None
    if (cfg.zoho_sync_enabled and cfg.zoho_mcp_url) or cfg.geocoding_enabled:
        worker = SyncWorker(cfg)
        worker.start()
    else:
        logging.getLogger("zoho").info("Background worker is OFF (no Zoho sync and no place lookup)")
    if not (cfg.zoho_sync_enabled and cfg.zoho_mcp_url):
        logging.getLogger("zoho").info("Zoho sync is OFF (ZOHO_MCP_URL not set or sync disabled)")
    yield
    if worker:
        worker.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="CapScout - Lead Screening", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(auth.router, prefix="/api")
    app.include_router(meta.router, prefix="/api")
    app.include_router(geo.router, prefix="/api")
    app.include_router(customers.router, prefix="/api")
    app.include_router(meetings.router, prefix="/api")
    app.include_router(meetings.new_lead_router, prefix="/api")

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict:
        return {"ok": True}

    return app


app = create_app()
