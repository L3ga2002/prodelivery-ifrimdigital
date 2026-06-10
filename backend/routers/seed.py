from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone, timedelta
import os
import secrets
from database import db
from auth import get_current_user, hash_password
from models.user import User
from models.driver import Driver
from models.restaurant import Restaurant
from models.order import Order

router = APIRouter(tags=["seed"])
SYSTEM_RANDOM = secrets.SystemRandom()


def _ensure_seed_allowed(current_user: dict) -> None:
    if os.environ.get("ALLOW_SEED", "").strip().lower() != "true":
        raise HTTPException(status_code=403, detail="Seed endpoint is disabled")
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")


def _get_demo_credentials() -> dict:
    return {
        "admin": {
            "email": os.environ["DEMO_ADMIN_EMAIL"],
            "password": os.environ["DEMO_ADMIN_PASSWORD"],
        },
        "driver_1": {
            "email": os.environ["DEMO_DRIVER_1_EMAIL"],
            "password": os.environ["DEMO_DRIVER_PASSWORD"],
        },
        "driver_2": {
            "email": os.environ["DEMO_DRIVER_2_EMAIL"],
            "password": os.environ["DEMO_DRIVER_PASSWORD"],
        },
        "restaurant_1": {
            "email": os.environ["DEMO_RESTAURANT_1_EMAIL"],
            "password": os.environ["DEMO_RESTAURANT_PASSWORD"],
        },
    }


def weighted_choice(options: list[str], weights: list[int]) -> str:
    threshold = SYSTEM_RANDOM.randrange(sum(weights))
    cumulative = 0
    for option, weight in zip(options, weights):
        cumulative += weight
        if threshold < cumulative:
            return option
    return options[-1]

ZONE_COLORS = {
    1: "#2563eb",
    2: "#f59e0b",
    3: "#dc2626",
}

ZONE_FEES = {
    1: 14.0,
    2: 22.0,
    3: 33.0,
}


def build_restaurant_zone_polygon(lat: float, lng: float, radius: float) -> list[dict]:
    return [
        {"lat": lat + radius, "lng": lng - radius},
        {"lat": lat + radius, "lng": lng + radius},
        {"lat": lat - radius, "lng": lng + radius},
        {"lat": lat - radius, "lng": lng - radius},
    ]


async def seed_demo_orders(drivers_data: list[dict]) -> int:
    first_names = ["Alexandru", "Maria", "Ion", "Elena", "Andrei", "Ana", "Mihai", "Cristina", "Bogdan", "Diana",
                   "Vlad", "Ioana", "George", "Raluca", "Dan", "Adriana", "Florin", "Simona", "Radu", "Laura",
                   "Stefan", "Gabriela", "Marius", "Alina", "Cosmin", "Monica", "Adrian", "Daniela", "Ciprian", "Roxana"]
    last_names = ["Popescu", "Ionescu", "Popa", "Dumitrescu", "Stan", "Gheorghe", "Stoica", "Marin", "Constantin", "Dinu",
                  "Radu", "Marinescu", "Voicu", "Matei", "Florea", "Rusu", "Munteanu", "Mihai", "Nistor", "Tudor"]
    streets = ["Calea Mărășești", "Str. Republicii", "Str. 9 Mai", "Bd. Unirii", "Str. Mihai Eminescu",
               "Str. Nicolae Bălcescu", "Str. Vasile Alecsandri", "Str. George Bacovia", "Calea Romanului",
               "Str. Alexandru cel Bun", "Str. Letea", "Str. Ștefan cel Mare", "Aleea Parcului",
               "Str. Mărășești", "Str. Pictor Aman", "Str. Costache Negri", "Str. Tecuciului"]
    food_items = {
        "rest-001": [{"name": "Pizza Margherita", "price": 35.0}, {"name": "Pizza Quattro Stagioni", "price": 45.0}, {"name": "Pizza Diavola", "price": 42.0}, {"name": "Paste Carbonara", "price": 38.0}, {"name": "Tiramisu", "price": 22.0}, {"name": "Bruschette", "price": 18.0}, {"name": "Cola 500ml", "price": 8.0}],
        "rest-002": [{"name": "Ciorbă de burtă", "price": 25.0}, {"name": "Sarmale cu mămăligă", "price": 32.0}, {"name": "Mici 10 buc", "price": 35.0}, {"name": "Tochitura moldovenească", "price": 38.0}, {"name": "Papanași", "price": 22.0}, {"name": "Plăcintă cu brânză", "price": 18.0}],
        "rest-003": [{"name": "Sushi Set 24 piese", "price": 95.0}, {"name": "Sushi Set 12 piese", "price": 55.0}, {"name": "Sashimi Salmon", "price": 45.0}, {"name": "Ramen Tonkotsu", "price": 42.0}, {"name": "Edamame", "price": 15.0}, {"name": "Gyoza 8 buc", "price": 28.0}],
        "rest-004": [{"name": "Burger Classic", "price": 28.0}, {"name": "Burger BBQ Smoky", "price": 35.0}, {"name": "Cheeseburger Deluxe", "price": 32.0}, {"name": "Cartofi Prăjiți", "price": 14.0}, {"name": "Onion Rings", "price": 16.0}, {"name": "Milkshake Oreo", "price": 20.0}],
        "rest-005": [{"name": "Ciorbă rădăuțeană", "price": 28.0}, {"name": "Frigărui de porc", "price": 35.0}, {"name": "Ceafă la grătar", "price": 42.0}, {"name": "Salată moldovenească", "price": 18.0}, {"name": "Cozonac de casă", "price": 15.0}, {"name": "Vin de casă 500ml", "price": 25.0}],
    }
    notes_options = ["", "", "", "", "Etaj 3, sună la interfon", "Să sune când ajunge jos", "Fără ardei iute", "Livrare la poartă", "Bloc nou, intrarea din spate", "Apartament la parter", "Să aducă și șervețele extra", "Fără ceapă", "Plată exact, nu am rest"]
    sources = ["S", "G", "W", "B"]
    source_weights = [30, 35, 25, 10]
    restaurants_ids = ["rest-001", "rest-002", "rest-003", "rest-004", "rest-005"]
    restaurant_names = {"rest-001": "Trattoria Da Vinci", "rest-002": "La Cuptor Bacău", "rest-003": "Sushi Room", "rest-004": "Burger Craft", "rest-005": "Casa Moldoveanu"}

    for i in range(1, 101):
        source = weighted_choice(sources, source_weights)
        restaurant_id = SYSTEM_RANDOM.choice(restaurants_ids)
        order_data, created_at, delivered_at = build_demo_order_payload(
            i, source, restaurant_id, restaurant_names, food_items, first_names,
            last_names, streets, notes_options, drivers_data,
        )
        order = Order(**order_data)
        doc = order.model_dump()
        doc["created_at"] = created_at.isoformat()
        doc["updated_at"] = delivered_at.isoformat() if order_data["status"] == "DELIVERED" else created_at.isoformat()
        await db.orders.insert_one(doc)
    return 100


async def seed_demo_map_routes() -> int:
    route_orders = [
        {
            "id": "demo-route-001",
            "order_number": "LIVE.101",
            "restaurant_id": "rest-001",
            "restaurant_name": "Trattoria Da Vinci",
            "driver_id": "driver-001",
            "driver_name": "Ion Popescu",
            "customer_name": "Client Centru Nord",
            "customer_phone": "0711111101",
            "customer_address": "Str. Ștefan cel Mare 18, Bacău",
            "customer_latitude": 46.5758,
            "customer_longitude": 26.9268,
            "status": "PICKED_UP",
            "total_amount": 86.0,
            "payment_type": "CARD",
            "source": "S",
        },
        {
            "id": "demo-route-002",
            "order_number": "LIVE.102",
            "restaurant_id": "rest-004",
            "restaurant_name": "Burger Craft",
            "driver_id": "driver-002",
            "driver_name": "Maria Ionescu",
            "customer_name": "Client Șerbănești",
            "customer_phone": "0711111102",
            "customer_address": "Str. Milcov 42, Bacău",
            "customer_latitude": 46.5872,
            "customer_longitude": 26.9344,
            "status": "ACCEPTED",
            "total_amount": 72.0,
            "payment_type": "CASH",
            "source": "G",
        },
        {
            "id": "demo-route-003",
            "order_number": "LIVE.103",
            "restaurant_id": "rest-003",
            "restaurant_name": "Sushi Room",
            "driver_id": "driver-005",
            "driver_name": "Bogdan Stanescu",
            "customer_name": "Client Letea",
            "customer_phone": "0711111103",
            "customer_address": "Str. Letea 61, Bacău",
            "customer_latitude": 46.5488,
            "customer_longitude": 26.9352,
            "status": "ASSIGNED",
            "total_amount": 118.0,
            "payment_type": "CARD",
            "source": "W",
        },
    ]
    now = datetime.now(timezone.utc).isoformat()
    await db.orders.delete_many({"id": {"$in": [order["id"] for order in route_orders]}})
    for order in route_orders:
        await db.orders.insert_one({
            **order,
            "items": [{"name": "Demo traseu client", "quantity": 1, "price": order["total_amount"]}],
            "subtotal_amount": order["total_amount"] - 10,
            "delivery_fee": 10,
            "notes": "Comandă demo pentru prezentare hartă live",
            "zone": "Demo Live",
            "delivery_zone_name": "Demo Live",
            "assigned_at": now,
            "accepted_at": now if order["status"] in ["ACCEPTED", "PICKED_UP"] else None,
            "picked_up_at": now if order["status"] == "PICKED_UP" else None,
            "created_at": now,
            "updated_at": now,
        })

    await db.drivers.update_many(
        {"id": {"$in": ["driver-001", "driver-002", "driver-005"]}},
        {"$set": {"is_active": True, "driver_status": "delivery"}},
    )
    await db.drivers.update_one({"id": "driver-001"}, {"$set": {"current_order_id": "demo-route-001", "vehicle_type": "scooter", "latitude": 46.5634, "longitude": 26.9105}})
    await db.drivers.update_one({"id": "driver-002"}, {"$set": {"current_order_id": "demo-route-002", "vehicle_type": "car", "latitude": 46.5692, "longitude": 26.9132}})
    await db.drivers.update_one({"id": "driver-005"}, {"$set": {"current_order_id": "demo-route-003", "vehicle_type": "car", "latitude": 46.5568, "longitude": 26.9188}})
    return len(route_orders)


async def clear_demo_collections() -> None:
    await db.users.delete_many({"role": {"$ne": "admin"}})
    await db.drivers.delete_many({})
    await db.restaurants.delete_many({})
    await db.orders.delete_many({})
    await db.emergency_slots.delete_many({})
    await db.schedules.delete_many({})
    await db.delivery_zones.delete_many({})


async def seed_admin_account(demo_credentials: dict) -> None:
    admin = User(id="admin-001", email=demo_credentials["admin"]["email"], name="Administrator", role="admin")
    admin_doc = admin.model_dump()
    admin_doc["password_hash"] = hash_password(demo_credentials["admin"]["password"])
    admin_doc["created_at"] = admin_doc["created_at"].isoformat()
    await db.users.update_one({"id": "admin-001"}, {"$set": admin_doc}, upsert=True)


async def seed_driver_accounts(drivers_data: list[dict], driver_email_map: dict, demo_credentials: dict) -> None:
    for driver_seed in drivers_data:
        user = User(
            id=f"user-{driver_seed['id']}",
            email=driver_email_map.get(driver_seed["id"], f"{driver_seed['id']}@delivery.ro"),
            name=driver_seed["name"],
            role="driver",
            phone=driver_seed["phone"],
        )
        user_doc = user.model_dump()
        user_doc["password_hash"] = hash_password(demo_credentials["driver_1"]["password"])
        joined_at = datetime.now(timezone.utc) - timedelta(days=driver_seed["joined_days_ago"])
        user_doc["created_at"] = joined_at.isoformat()
        await db.users.insert_one(user_doc)

        driver = Driver(
            id=driver_seed["id"],
            user_id=user.id,
            name=driver_seed["name"],
            phone=driver_seed["phone"],
            is_active=driver_seed["active"],
            vehicle_type=driver_seed.get("vehicle_type", "scooter"),
            latitude=driver_seed["lat"],
            longitude=driver_seed["lng"],
            total_deliveries=driver_seed["deliveries"],
            punctuality_rate=driver_seed["punctuality"],
            joined_at=joined_at.isoformat(),
        )
        await db.drivers.insert_one(driver.model_dump())


async def seed_restaurant_accounts(restaurants_data: list[dict], restaurant_email_map: dict, demo_credentials: dict) -> None:
    for restaurant_seed in restaurants_data:
        restaurant = Restaurant(**restaurant_seed)
        await db.restaurants.insert_one(restaurant.model_dump())

        rest_user = User(
            id=f"user-{restaurant_seed['id']}",
            email=restaurant_email_map.get(restaurant_seed["id"], f"{restaurant_seed['id']}@delivery.ro"),
            name=restaurant_seed["name"],
            role="restaurant",
            phone=restaurant_seed["phone"],
            restaurant_id=restaurant_seed["id"],
            restaurant_name=restaurant_seed["name"],
        )
        rest_user_doc = rest_user.model_dump()
        rest_user_doc["password_hash"] = hash_password(demo_credentials["restaurant_1"]["password"])
        rest_user_doc["created_at"] = rest_user_doc["created_at"].isoformat()
        await db.users.insert_one(rest_user_doc)


async def seed_delivery_zones(restaurants_data: list[dict]) -> None:
    sort_order = 1
    for restaurant_seed in restaurants_data:
        for zone_level, radius in [(1, 0.015), (2, 0.026)]:
            await db.delivery_zones.insert_one({
                "id": f"{restaurant_seed['id']}-zone-{zone_level}",
                "restaurant_id": restaurant_seed["id"],
                "restaurant_name": restaurant_seed["name"],
                "sector": restaurant_seed["name"],
                "zone_level": zone_level,
                "name": "Aproape" if zone_level == 1 else "Extinsă",
                "color": ZONE_COLORS[zone_level],
                "fee": 10.0 if zone_level == 1 else 18.0,
                "is_active": True,
                "sort_order": sort_order,
                "polygon": build_restaurant_zone_polygon(restaurant_seed["latitude"], restaurant_seed["longitude"], radius),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            sort_order += 1


def build_demo_order_payload(
    index: int,
    source: str,
    restaurant_id: str,
    restaurant_names: dict,
    food_items: dict,
    first_names: list[str],
    last_names: list[str],
    streets: list[str],
    notes_options: list[str],
    drivers_data: list[dict],
) -> tuple[dict, datetime, datetime]:
    first_name = SYSTEM_RANDOM.choice(first_names)
    last_name = SYSTEM_RANDOM.choice(last_names)
    customer_name = f"{first_name} {last_name}"
    customer_phone = f"07{SYSTEM_RANDOM.randint(20, 99)}{SYSTEM_RANDOM.randint(100000, 999999)}"
    customer_address = f"{SYSTEM_RANDOM.choice(streets)} {SYSTEM_RANDOM.randint(1, 150)}, Ap. {SYSTEM_RANDOM.randint(1, 50)}, Bacău"
    selected_items = SYSTEM_RANDOM.sample(food_items[restaurant_id], min(SYSTEM_RANDOM.randint(1, 4), len(food_items[restaurant_id])))
    items = []
    total = 0
    for item in selected_items:
        qty = SYSTEM_RANDOM.randint(1, 3)
        items.append({"name": item["name"], "quantity": qty, "price": item["price"]})
        total += item["price"] * qty

    created_at = datetime.now(timezone.utc) - timedelta(hours=SYSTEM_RANDOM.randint(1, 24 * 45))
    prep_estimated_seconds = SYSTEM_RANDOM.choice([10, 15, 20, 25, 30]) * 60
    prep_actual_seconds = max(prep_estimated_seconds + SYSTEM_RANDOM.randint(-240, 600), 120)
    prep_delay_seconds = max(prep_actual_seconds - prep_estimated_seconds, 0)
    preparation_started_at = created_at + timedelta(minutes=2)
    preparation_due_at = preparation_started_at + timedelta(seconds=prep_estimated_seconds)
    preparation_ready_at = preparation_started_at + timedelta(seconds=prep_actual_seconds)
    assigned_at = preparation_ready_at + timedelta(minutes=SYSTEM_RANDOM.randint(1, 8))
    accepted_at = assigned_at + timedelta(minutes=SYSTEM_RANDOM.randint(1, 4))
    picked_up_at = accepted_at + timedelta(minutes=SYSTEM_RANDOM.randint(2, 8))
    delivered_at = picked_up_at + timedelta(minutes=SYSTEM_RANDOM.randint(12, 35))

    driver_id = None
    driver_name = None
    status = "NEW"
    if index <= 40:
        driver = drivers_data[(index - 1) % 5]
        driver_id = driver["id"]
        driver_name = driver["name"]
        status = "DELIVERED"

    zone_map = {"rest-001": "Zona 1", "rest-002": "Zona 2", "rest-003": "Zona 3", "rest-004": "Zona 4", "rest-005": "Zona 1"}
    return {
        "order_number": f"{source}.{index:04d}",
        "source": source,
        "restaurant_id": restaurant_id,
        "restaurant_name": restaurant_names[restaurant_id],
        "customer_name": customer_name,
        "customer_phone": customer_phone,
        "customer_address": customer_address,
        "items": items,
        "total_amount": total,
        "payment_type": SYSTEM_RANDOM.choice(["CASH", "CASH", "CARD"]),
        "notes": SYSTEM_RANDOM.choice(notes_options),
        "status": status,
        "zone": zone_map.get(restaurant_id, "Zona 1"),
        "driver_id": driver_id,
        "driver_name": driver_name,
        "preparation_time": prep_estimated_seconds // 60,
        "preparation_estimated_seconds": prep_estimated_seconds,
        "preparation_actual_seconds": prep_actual_seconds if status == "DELIVERED" else None,
        "preparation_delay_seconds": prep_delay_seconds if status == "DELIVERED" else None,
        "preparation_started_at": preparation_started_at.isoformat(),
        "preparation_due_at": preparation_due_at.isoformat(),
        "preparation_ready_at": preparation_ready_at.isoformat() if status == "DELIVERED" else None,
        "assigned_at": assigned_at.isoformat() if status == "DELIVERED" else None,
        "accepted_at": accepted_at.isoformat() if status == "DELIVERED" else None,
        "picked_up_at": picked_up_at.isoformat() if status == "DELIVERED" else None,
        "delivered_at": delivered_at.isoformat() if status == "DELIVERED" else None,
    }, created_at, delivered_at


SECTOR_MAPS = [
    {
        "sector": "Nord",
        "source_map": "https://s.go.ro/fb57ezyt",
        "polygons": {
            1: [
                {"lat": 46.579000, "lng": 26.896000},
                {"lat": 46.585000, "lng": 26.900000},
                {"lat": 46.591000, "lng": 26.903500},
                {"lat": 46.596000, "lng": 26.911500},
                {"lat": 46.595000, "lng": 26.920500},
                {"lat": 46.590000, "lng": 26.928000},
                {"lat": 46.583000, "lng": 26.928500},
                {"lat": 46.578000, "lng": 26.920000},
                {"lat": 46.576000, "lng": 26.907500},
            ],
            2: [
                {"lat": 46.573000, "lng": 26.889000},
                {"lat": 46.582000, "lng": 26.893000},
                {"lat": 46.593000, "lng": 26.897000},
                {"lat": 46.603000, "lng": 26.907500},
                {"lat": 46.603000, "lng": 26.921500},
                {"lat": 46.596000, "lng": 26.934500},
                {"lat": 46.583000, "lng": 26.937000},
                {"lat": 46.573000, "lng": 26.929500},
                {"lat": 46.569000, "lng": 26.912000},
            ],
            3: [
                {"lat": 46.566000, "lng": 26.881000},
                {"lat": 46.579000, "lng": 26.887000},
                {"lat": 46.596000, "lng": 26.890500},
                {"lat": 46.610000, "lng": 26.903500},
                {"lat": 46.611000, "lng": 26.924000},
                {"lat": 46.602000, "lng": 26.941000},
                {"lat": 46.585000, "lng": 26.947000},
                {"lat": 46.570000, "lng": 26.937000},
                {"lat": 46.564000, "lng": 26.917000},
            ],
        },
    },
    {
        "sector": "Centru",
        "source_map": "https://s.go.ro/yctb1v1x",
        "polygons": {
            1: [
                {"lat": 46.562000, "lng": 26.902000},
                {"lat": 46.570000, "lng": 26.904000},
                {"lat": 46.577000, "lng": 26.909500},
                {"lat": 46.579000, "lng": 26.917500},
                {"lat": 46.575000, "lng": 26.924500},
                {"lat": 46.568000, "lng": 26.927500},
                {"lat": 46.560000, "lng": 26.923500},
                {"lat": 46.557000, "lng": 26.914000},
            ],
            2: [
                {"lat": 46.556000, "lng": 26.895000},
                {"lat": 46.568000, "lng": 26.897000},
                {"lat": 46.580000, "lng": 26.904500},
                {"lat": 46.584000, "lng": 26.915500},
                {"lat": 46.580000, "lng": 26.927500},
                {"lat": 46.569000, "lng": 26.934500},
                {"lat": 46.556000, "lng": 26.931500},
                {"lat": 46.549000, "lng": 26.919500},
                {"lat": 46.549000, "lng": 26.904000},
            ],
            3: [
                {"lat": 46.549000, "lng": 26.888000},
                {"lat": 46.565000, "lng": 26.890500},
                {"lat": 46.583000, "lng": 26.900500},
                {"lat": 46.590000, "lng": 26.915500},
                {"lat": 46.584000, "lng": 26.932500},
                {"lat": 46.569000, "lng": 26.941500},
                {"lat": 46.551000, "lng": 26.938500},
                {"lat": 46.542000, "lng": 26.922500},
                {"lat": 46.543000, "lng": 26.902000},
            ],
        },
    },
    {
        "sector": "Sud",
        "source_map": "https://s.go.ro/8j1ugnus",
        "polygons": {
            1: [
                {"lat": 46.547000, "lng": 26.901000},
                {"lat": 46.554000, "lng": 26.904000},
                {"lat": 46.559000, "lng": 26.910500},
                {"lat": 46.560000, "lng": 26.919500},
                {"lat": 46.556000, "lng": 26.926500},
                {"lat": 46.549000, "lng": 26.929500},
                {"lat": 46.543000, "lng": 26.924500},
                {"lat": 46.541000, "lng": 26.915000},
            ],
            2: [
                {"lat": 46.541000, "lng": 26.894000},
                {"lat": 46.551000, "lng": 26.897500},
                {"lat": 46.561000, "lng": 26.903500},
                {"lat": 46.566000, "lng": 26.914500},
                {"lat": 46.563000, "lng": 26.928500},
                {"lat": 46.553000, "lng": 26.936500},
                {"lat": 46.541000, "lng": 26.935500},
                {"lat": 46.535000, "lng": 26.923500},
                {"lat": 46.535000, "lng": 26.907000},
            ],
            3: [
                {"lat": 46.534000, "lng": 26.886000},
                {"lat": 46.548000, "lng": 26.891500},
                {"lat": 46.563000, "lng": 26.899500},
                {"lat": 46.571000, "lng": 26.913500},
                {"lat": 46.567000, "lng": 26.931500},
                {"lat": 46.554000, "lng": 26.942500},
                {"lat": 46.537000, "lng": 26.941500},
                {"lat": 46.529000, "lng": 26.925500},
                {"lat": 46.528000, "lng": 26.905000},
            ],
        },
    },
    {
        "sector": "Nord Extrem",
        "source_map": "https://s.go.ro/4t7zgqrk",
        "polygons": {
            1: [
                {"lat": 46.596000, "lng": 26.878000},
                {"lat": 46.602000, "lng": 26.882500},
                {"lat": 46.607000, "lng": 26.888500},
                {"lat": 46.609000, "lng": 26.897500},
                {"lat": 46.606000, "lng": 26.906500},
                {"lat": 46.600000, "lng": 26.911500},
                {"lat": 46.593000, "lng": 26.906500},
                {"lat": 46.590000, "lng": 26.896000},
            ],
            2: [
                {"lat": 46.590000, "lng": 26.868000},
                {"lat": 46.600000, "lng": 26.874000},
                {"lat": 46.610000, "lng": 26.882500},
                {"lat": 46.615000, "lng": 26.895500},
                {"lat": 46.611000, "lng": 26.909500},
                {"lat": 46.601000, "lng": 26.918500},
                {"lat": 46.589000, "lng": 26.913500},
                {"lat": 46.583000, "lng": 26.898500},
                {"lat": 46.584000, "lng": 26.881000},
            ],
            3: [
                {"lat": 46.584000, "lng": 26.856000},
                {"lat": 46.597000, "lng": 26.865000},
                {"lat": 46.612000, "lng": 26.874500},
                {"lat": 46.621000, "lng": 26.892500},
                {"lat": 46.616000, "lng": 26.912500},
                {"lat": 46.602000, "lng": 26.924500},
                {"lat": 46.585000, "lng": 26.919500},
                {"lat": 46.576000, "lng": 26.900500},
                {"lat": 46.577000, "lng": 26.876000},
            ],
        },
    },
]


@router.post("/seed")
async def seed_data(current_user: dict = Depends(get_current_user)):
    _ensure_seed_allowed(current_user)
    demo_credentials = _get_demo_credentials()
    driver_email_map = {
        "driver-001": demo_credentials["driver_1"]["email"],
        "driver-002": demo_credentials["driver_2"]["email"],
    }
    restaurant_email_map = {
        "rest-001": demo_credentials["restaurant_1"]["email"],
    }

    await clear_demo_collections()
    await seed_admin_account(demo_credentials)

    # Drivers
    drivers_data = [
        {"id": "driver-001", "name": "Ion Popescu", "phone": "0722111222", "lat": 46.5690, "lng": 26.9100, "active": True, "deliveries": 142, "punctuality": 0.97, "joined_days_ago": 720, "vehicle_type": "scooter"},
        {"id": "driver-002", "name": "Maria Ionescu", "phone": "0722333444", "lat": 46.5640, "lng": 26.9180, "active": True, "deliveries": 108, "punctuality": 0.93, "joined_days_ago": 510, "vehicle_type": "car"},
        {"id": "driver-003", "name": "Andrei Popa", "phone": "0722555666", "lat": 46.5730, "lng": 26.9050, "active": False, "deliveries": 68, "punctuality": 0.89, "joined_days_ago": 300},
        {"id": "driver-004", "name": "Elena Dumitrescu", "phone": "0722777888", "lat": 46.5580, "lng": 26.9220, "active": True, "deliveries": 36, "punctuality": 0.84, "joined_days_ago": 150},
        {"id": "driver-005", "name": "Bogdan Stanescu", "phone": "0722999000", "lat": 46.5710, "lng": 26.9150, "active": True, "deliveries": 12, "punctuality": 0.78, "joined_days_ago": 45, "vehicle_type": "car"},
    ]

    await seed_driver_accounts(drivers_data, driver_email_map, demo_credentials)

    # Restaurants
    restaurants_data = [
        {"id": "rest-001", "name": "Trattoria Da Vinci", "address": "Calea Mărășești 12, Bacău", "phone": "0234111222", "latitude": 46.5670, "longitude": 26.9135},
        {"id": "rest-002", "name": "La Cuptor Bacău", "address": "Str. Republicii 34, Bacău", "phone": "0234333444", "latitude": 46.5720, "longitude": 26.9070},
        {"id": "rest-003", "name": "Sushi Room", "address": "Str. 9 Mai 18, Bacău", "phone": "0234555666", "latitude": 46.5610, "longitude": 26.9200},
        {"id": "rest-004", "name": "Burger Craft", "address": "Bd. Unirii 56, Bacău", "phone": "0234777888", "latitude": 46.5750, "longitude": 26.9165},
        {"id": "rest-005", "name": "Casa Moldoveanu", "address": "Str. Mihai Eminescu 8, Bacău", "phone": "0234999111", "latitude": 46.5630, "longitude": 26.9060},
    ]

    await seed_restaurant_accounts(restaurants_data, restaurant_email_map, demo_credentials)
    await seed_delivery_zones(restaurants_data)

    await seed_demo_orders(drivers_data)
    demo_routes = await seed_demo_map_routes()

    return {
        "message": "Demo data seeded successfully - 100 orders created",
        "data": {"orders": 100 + demo_routes, "drivers": 5, "restaurants": 5, "demo_routes": demo_routes}
    }
