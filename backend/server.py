from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from fastapi import FastAPI
from starlette.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
import os
import logging

from database import db, client
from routers import auth, drivers, restaurants, orders, stats, seed, schedules, emergency_slots, zones, geocoding

app = FastAPI(title="Delivery Platform API")


def _parse_cors_origins() -> list[str]:
    return [origin.strip() for origin in os.environ['CORS_ORIGINS'].split(',') if origin.strip()]

# API prefix wrapper
from fastapi import APIRouter
api_router = APIRouter(prefix="/api")

# Include all sub-routers into the api_router
api_router.include_router(auth.router)
api_router.include_router(drivers.router)
api_router.include_router(restaurants.router)
api_router.include_router(orders.router)
api_router.include_router(stats.router)
api_router.include_router(seed.router)
api_router.include_router(schedules.router)
api_router.include_router(emergency_slots.router)
api_router.include_router(zones.router)
api_router.include_router(geocoding.router)


@api_router.get("/")
async def root() -> dict[str, str]:
    return {"message": "Delivery Platform API v2.0", "status": "running"}


app.include_router(api_router)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=_parse_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_CORS_ORIGINS = set(_parse_cors_origins())
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def enforce_explicit_cors_origin(request, call_next):
    response = await call_next(request)
    origin = request.headers.get("origin")
    if origin in ALLOWED_CORS_ORIGINS:
        response.headers["access-control-allow-origin"] = origin
        response.headers["access-control-allow-credentials"] = "true"
        existing_vary = response.headers.get("vary")
        if existing_vary:
            if "origin" not in existing_vary.lower():
                response.headers["vary"] = f"{existing_vary}, Origin"
        else:
            response.headers["vary"] = "Origin"
    return response


@app.middleware("http")
async def reject_untrusted_unsafe_origins(request, call_next):
    origin = request.headers.get("origin")
    if request.method in UNSAFE_METHODS and origin and origin not in ALLOWED_CORS_ORIGINS:
        return JSONResponse({"detail": "Untrusted request origin"}, status_code=403)
    return await call_next(request)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@app.on_event("shutdown")
async def shutdown_db_client() -> None:
    client.close()
