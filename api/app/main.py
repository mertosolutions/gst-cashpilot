import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.controllers import copilot, dashboard, draft, ingest, pipeline, reconciliation, scans, system, vendors, voice, live
from app.core.config import get_settings
from app.core.database import SessionLocal

settings = get_settings()


def _warm_up():
    try:
        from app.controllers.live import _live_config
        from app.services import gemini
        if gemini.available():
            gemini._client()
            _live_config()
    except Exception:  # warm-up is best effort
        pass


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.core.database import Base, engine
    from app.seed.load import seed
    from app.services import rag
    import app.models  # noqa: F401
    Base.metadata.create_all(engine)  # no-op when the tables exist (AlloyDB is prepared by scripts/alloydb_setup.py)
    with SessionLocal() as db:
        rag.ensure_rules_loaded(db)  # the shared GST rule passages every business cites
    if settings.auto_seed:
        with SessionLocal() as db:
            seed(db)
    asyncio.get_running_loop().run_in_executor(None, _warm_up)  # first voice connection should not pay the import cost
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan,
              description="GST CashPilot: pre-filing GST checks. Draft only, nothing is filed.")
@app.middleware("http")
async def clear_cache_after_writes(request, call_next):
    response = await call_next(request)
    if request.method not in ("GET", "HEAD", "OPTIONS") and response.status_code < 400:
        from app.core import cache
        cache.clear()  # data may have changed: drop the cached dashboard results
    return response


app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_origin_regex=r"https://.*\.(web\.app|firebaseapp\.com)", allow_methods=["*"], allow_headers=["*"])

for r in (system.router, dashboard.router, vendors.router, reconciliation.router, pipeline.router, draft.router, scans.router, ingest.router, copilot.router, voice.router, live.router):
    app.include_router(r, prefix=settings.api_prefix)


@app.get("/")
def root():
    return {"name": settings.app_name, "docs": "/docs", "status": f"{settings.api_prefix}/system/status"}
