import asyncio
import os
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from auth import get_current_user

router = APIRouter(prefix="/geocoding", tags=["geocoding"])

NOMINATIM_BASE_URL = os.environ["NOMINATIM_BASE_URL"]
NOMINATIM_USER_AGENT = os.environ["NOMINATIM_USER_AGENT"]
BACAU_VIEWBOX = os.environ["NOMINATIM_BACAU_VIEWBOX"]

_cache: dict[str, tuple[float, list[dict]]] = {}
_lock = asyncio.Lock()
_last_request_at = 0.0
CACHE_TTL_SECONDS = 3600


def _cache_get(key: str) -> list[dict] | None:
    entry = _cache.get(key)
    if not entry:
        return None
    created_at, data = entry
    if time.time() - created_at > CACHE_TTL_SECONDS:
        _cache.pop(key, None)
        return None
    return data


def _cache_set(key: str, data: list[dict]) -> None:
    _cache[key] = (time.time(), data)


async def _rate_limit() -> None:
    global _last_request_at
    async with _lock:
        elapsed = time.time() - _last_request_at
        if elapsed < 1.05:
            await asyncio.sleep(1.05 - elapsed)
        _last_request_at = time.time()


def _format_result(item: dict) -> dict:
    return {
        "place_id": item.get("place_id"),
        "label": item.get("display_name", ""),
        "name": item.get("name") or item.get("display_name", "").split(",")[0],
        "lat": float(item.get("lat", 0)),
        "lng": float(item.get("lon", 0)),
        "type": item.get("type"),
        "address_type": item.get("addresstype") or item.get("address_type"),
        "importance": item.get("importance", 0),
    }


@router.get("/search")
async def search_locations(
    q: str = Query(..., min_length=2, max_length=180),
    limit: int = Query(6, ge=1, le=10),
    current_user: dict = Depends(get_current_user),
):
    cache_key = f"{q.strip().lower()}:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return {"suggestions": cached, "source": "cache"}

    await _rate_limit()
    params = {
        "q": f"{q}, Bacău, România",
        "format": "jsonv2",
        "limit": limit,
        "countrycodes": "ro",
        "addressdetails": 1,
        "viewbox": BACAU_VIEWBOX,
        "bounded": 0,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            response = await client.get(
                f"{NOMINATIM_BASE_URL}/search",
                params=params,
                headers={"User-Agent": NOMINATIM_USER_AGENT},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Geocoding unavailable") from exc

    suggestions = [_format_result(item) for item in response.json()]
    _cache_set(cache_key, suggestions)
    return {"suggestions": suggestions, "source": "api"}
