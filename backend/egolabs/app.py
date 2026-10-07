from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from egolabs import __version__
from egolabs.api import (
    admin,
    annotations,
    assignments,
    auth,
    cv,
    datasets,
    devices,
    health,
    jobs,
    movement,
    overview,
    pipelines,
    review,
    sessions,
    uploads,
    users,
    videos,
)
from egolabs.config import get_settings
from egolabs.logs import configure_logging

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="Ego Labs API", version=__version__, openapi_url=f"{API_PREFIX}/openapi.json")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api = APIRouter(prefix=API_PREFIX)
    for module in (
        health, auth, admin, assignments, users, overview, jobs, uploads, sessions, videos, devices, datasets, annotations, cv, movement, review,
        pipelines,
    ):  # fmt: skip
        api.include_router(module.router)
    api.include_router(pipelines.videos_router)
    app.include_router(api)
    return app


app = create_app()
