from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.controllers import copilot, dashboard, draft, ingest, pipeline, reconciliation, scans, system, vendors, voice
from app.core.config import get_settings
from app.core.database import SessionLocal

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.seed.load import seed
    if settings.auto_seed:
        with SessionLocal() as db:
            seed(db)
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan,
              description="GST CashPilot: pre-filing GST checks. Draft only, nothing is filed.")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_origin_regex=r"https://.*\.(web\.app|firebaseapp\.com)", allow_methods=["*"], allow_headers=["*"])

for r in (system.router, dashboard.router, vendors.router, reconciliation.router, pipeline.router, draft.router, scans.router, ingest.router, copilot.router, voice.router):
    app.include_router(r, prefix=settings.api_prefix)


@app.get("/")
def root():
    return {"name": settings.app_name, "docs": "/docs", "status": f"{settings.api_prefix}/system/status"}
