from fastapi import APIRouter, HTTPException, Depends, Query
from datetime import datetime, timezone
from shapely.geometry import Point, Polygon
from database import db
from auth import get_current_user
from models.delivery_zone import DeliveryZone, DeliveryZoneCreate, DeliveryZoneUpdate, ZoneDetectRequest

router = APIRouter(prefix="/zones", tags=["zones"])

def ensure_admin(current_user: dict) -> None:
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")


def build_shapely_polygon(coords):
    if len(coords) < 3:
        return None
    ring = [(c["lng"], c["lat"]) for c in coords]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return Polygon(ring)


def build_zone_update_payload(data: DeliveryZoneUpdate, existing: dict) -> dict:
    update_data = {"updated_at": datetime.now(timezone.utc).isoformat()}
    scalar_fields = [
        "restaurant_id",
        "restaurant_name",
        "sector",
        "zone_level",
        "name",
        "color",
        "fee",
        "is_active",
        "sort_order",
        "is_locked",
    ]
    for field_name in scalar_fields:
        value = getattr(data, field_name)
        if value is not None:
            update_data[field_name] = value
    if data.polygon is not None:
        update_data["polygon"] = [{"lat": coord.lat, "lng": coord.lng} for coord in data.polygon]
    return update_data


def build_detect_response(zone: dict | None) -> dict:
    if zone:
        return {
            "zone_id": zone["id"],
            "zone_name": zone["name"],
            "restaurant_id": zone.get("restaurant_id"),
            "restaurant_name": zone.get("restaurant_name"),
            "sector": zone.get("sector"),
            "zone_level": zone.get("zone_level"),
            "fee": zone["fee"],
            "color": zone["color"],
        }

    return {
        "zone_id": None,
        "zone_name": "In afara zonelor",
        "restaurant_id": None,
        "restaurant_name": None,
        "sector": None,
        "zone_level": None,
        "fee": 0,
        "color": "#999999",
    }


@router.get("")
async def get_zones(
    restaurant_id: str | None = Query(default=None),
    include_legacy: bool = Query(default=False),
    current_user: dict = Depends(get_current_user),
):
    query = {}
    if restaurant_id:
        query["restaurant_id"] = restaurant_id
    elif not include_legacy:
        query["restaurant_id"] = {"$exists": True, "$ne": None}

    zones = await db.delivery_zones.find(query, {"_id": 0}).sort("sort_order", 1).to_list(1000)
    return zones


@router.get("/{zone_id}")
async def get_zone(zone_id: str, current_user: dict = Depends(get_current_user)):
    zone = await db.delivery_zones.find_one({"id": zone_id}, {"_id": 0})
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    return zone


@router.post("")
async def create_zone(data: DeliveryZoneCreate, current_user: dict = Depends(get_current_user)):
    ensure_admin(current_user)

    restaurant = await db.restaurants.find_one({"id": data.restaurant_id}, {"_id": 0})
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    zone = DeliveryZone(
        restaurant_id=data.restaurant_id,
        restaurant_name=data.restaurant_name or restaurant["name"],
        sector=data.sector,
        zone_level=data.zone_level,
        name=data.name,
        color=data.color,
        fee=data.fee,
        polygon=data.polygon,
        is_active=data.is_active,
        sort_order=data.sort_order,
        is_locked=True,
    )
    doc = zone.model_dump()
    doc["created_at"] = doc["created_at"].isoformat()
    doc["updated_at"] = doc["updated_at"].isoformat()
    doc["polygon"] = [{"lat": c.lat, "lng": c.lng} for c in zone.polygon]
    await db.delivery_zones.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/{zone_id}")
async def update_zone(zone_id: str, data: DeliveryZoneUpdate, current_user: dict = Depends(get_current_user)):
    ensure_admin(current_user)

    existing = await db.delivery_zones.find_one({"id": zone_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Zone not found")
    if existing.get("is_locked", True) and not data.confirm_protected_action:
        raise HTTPException(status_code=409, detail="Zona este blocată. Confirmă explicit modificarea pentru a continua.")

    update_data = build_zone_update_payload(data, existing)

    await db.delivery_zones.update_one({"id": zone_id}, {"$set": update_data})
    updated = await db.delivery_zones.find_one({"id": zone_id}, {"_id": 0})
    return updated


@router.delete("/{zone_id}")
async def delete_zone(
    zone_id: str,
    confirm_protected_action: bool = Query(default=False),
    current_user: dict = Depends(get_current_user),
):
    ensure_admin(current_user)

    existing = await db.delivery_zones.find_one({"id": zone_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Zone not found")
    if existing.get("is_locked", True) and not confirm_protected_action:
        raise HTTPException(status_code=409, detail="Zona este blocată. Confirmă explicit ștergerea pentru a continua.")

    result = await db.delivery_zones.delete_one({"id": zone_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Zone not found")
    return {"message": "Zone deleted"}


@router.post("/detect")
async def detect_zone(data: ZoneDetectRequest, current_user: dict = Depends(get_current_user)):
    point = Point(data.lng, data.lat)
    query = {"is_active": True, "restaurant_id": {"$exists": True, "$ne": None}}
    if data.restaurant_id:
        query["restaurant_id"] = data.restaurant_id
    zones = await db.delivery_zones.find(query, {"_id": 0}).to_list(1000)
    matches = []

    for zone in zones:
        coords = zone.get("polygon", [])
        poly = build_shapely_polygon(coords)
        if poly and poly.contains(point):
            matches.append((poly.area, zone))

    if matches:
        _, best_zone = sorted(matches, key=lambda item: item[0])[0]
        return build_detect_response(best_zone)

    return build_detect_response(None)


@router.delete("/legacy/global")
async def delete_legacy_global_zones(current_user: dict = Depends(get_current_user)):
    ensure_admin(current_user)
    result = await db.delivery_zones.delete_many({"restaurant_id": {"$exists": False}})
    return {"message": "Legacy global zones deleted", "deleted_count": result.deleted_count}
