"""FastAPI app factory. Run: python run.py backend
(= uvicorn --factory backend.main:create_app).

All data is SYNTHETIC. Endpoints answer with the ml result types; errors from the ml interfaces
(bad dates, unknown employees) become 422, things MOCK mode cannot answer become 404.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pymongo.database import Database

from backend import demo, loop
from backend.config import Settings, default_settings
from backend.db import audit, ensure_seeded
from backend.mongo import database_kind, get_database
from backend.roster import service as roster_service
from backend.schemas import (
    AttritionScore,
    ForecastResult,
    Health,
    RescoreRequest,
    RescoreResult,
    ScoreRequest,
)
from backend.services import MockService, ModelService, NotAvailable, Service, model_versions
from backend.tasks import api as task_api
from backend.tasks.engine import VirtualClock

CORS_ENV = "CORS_ORIGINS"


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_service(request: Request) -> Service:
    return request.app.state.service


def source_of(request: Request) -> str:
    return "api:mock" if request.app.state.settings.mock else "api"


def _guard(fn):  # noqa: ANN001, ANN202 - map ml / mock errors to HTTP errors
    try:
        return fn()
    except NotAvailable as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


def cors_origins() -> list[str]:
    """CORS_ORIGINS env var (comma-separated); default "*" = all origins (demo only)."""
    raw = os.environ.get(CORS_ENV, "*")
    return [o.strip() for o in raw.split(",") if o.strip()] or ["*"]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or default_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN202
        ensure_seeded(app.state.db, settings.config.data_source)  # indexes + seed if empty
        scheduler = task_api.start_scheduler(app)
        yield
        if scheduler is not None:
            scheduler.shutdown(wait=False)

    app = FastAPI(title="Hospitality Operations Intelligence (HOI) API (SYNTHETIC data)",
                  lifespan=lifespan)
    # CORS: relaxed to every origin by default for the hackathon demo, so a frontend hosted
    # elsewhere (e.g. Streamlit) can call the API. Set CORS_ORIGINS (comma-separated) to the
    # frontend's URL to restrict it. No cookies or credentials are used.
    app.add_middleware(CORSMiddleware, allow_origins=cors_origins(), allow_methods=["*"],
                       allow_headers=["*"], allow_credentials=False)
    app.state.settings = settings
    app.state.db = get_database(settings)  # pymongo connects lazily, on first use
    app.state.service = MockService() if settings.mock else ModelService()
    app.state.clock = VirtualClock()
    register_core_routes(app)
    app.include_router(roster_service.router(get_db, get_service, source_of))
    app.include_router(task_api.router(get_db, source_of))
    app.include_router(loop.router(get_db, get_service, source_of))
    app.include_router(demo.router(get_db, get_service, source_of))
    return app


def register_core_routes(app: FastAPI) -> None:
    @app.get("/health", response_model=Health)
    def health(request: Request) -> Health:
        settings = request.app.state.settings
        return Health(status="ok", mock=settings.mock, models=model_versions(),
                      database=database_kind(settings))

    @app.get("/forecast", response_model=ForecastResult)
    def forecast(start: date = Query(alias="from"), end: date = Query(alias="to"),
                 as_of: date | None = None, service: Service = Depends(get_service)
                 ) -> ForecastResult:
        return _guard(lambda: service.forecast(start, end, as_of))

    @app.post("/attrition/score", response_model=list[AttritionScore])
    def score(body: ScoreRequest, request: Request, service: Service = Depends(get_service),
              db: Database = Depends(get_db)) -> list[AttritionScore]:
        result = _guard(lambda: service.score(body.week_start, body.employee_ids))
        audit(db, "attrition.score", {"week_start": body.week_start, "n": len(result)},
              source_of(request))
        return result

    @app.post("/attrition/rescore", response_model=RescoreResult)
    def rescore(body: RescoreRequest, request: Request, service: Service = Depends(get_service),
                db: Database = Depends(get_db)) -> RescoreResult:
        result = _guard(lambda: service.rescore(body.employee_id, body.feature_overrides,
                                                body.week_start, body.protected_weekends_off))
        audit(db, "attrition.rescore",
              {"employee_id": body.employee_id, "risk_change": result.risk_change,
               "note": result.note}, source_of(request))
        return result

