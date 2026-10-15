"""Bounded financial discovery/quotes: read methods only, no admission side effects."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import math

from bson.int64 import Int64
from pydantic import ValidationError
from pymongo.errors import PyMongoError

from models.order_finance import RestaurantTariffVersion
from models.order_finance_preview import (
    AdminFinancePreview, CreateFinancePreview, FinanceCapabilities, FinancePreview,
    FinanceTariffs, RemakeFinancePreview,
)
from models.order_mutation import CreateOrderCommand
from models.order_remakes import RemakeCommand
from utils.order_creation import CreationError, OrderCreationService, _identity
from utils.order_finance import FinanceError, quote_at_admission, _digest, validate_snapshot
from utils.order_remakes import (
    OrderRemakeService, PARENT_FIELDS, CUSTODY_PARENT_FIELDS, _child_command, _policy,
    _validate_parent, _parent_snapshot,
)


logger = logging.getLogger(__name__)
DEADLINE_SECONDS = 8
MAX_TIME_MS = 2000
MAX_TARIFFS = 50
MAX_ZONES = 300
MAX_POINTS = 1000
PREVIEW_OPERATION = "read_only_preview"


@dataclass(frozen=True)
class PreparedRemakeConfirmation:
    parent_snapshot: dict
    child_command: CreateOrderCommand
    financial_snapshot: dict
    quote_fingerprint: str


def _error(code, status=409):
    return CreationError(status, code, "Previzualizarea financiara necesita verificare.")


def _identifier(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 120 or value != value.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise _error("INVALID_REQUEST", 422)
    return value


@asynccontextmanager
async def _bounded():
    try:
        async with asyncio.timeout(DEADLINE_SECONDS):
            yield
    except FinanceError as exc:
        raise _error(exc.code, exc.status_code) from None
    except (TimeoutError, PyMongoError):
        logger.warning("order_finance_preview_unavailable")
        raise _error("FINANCIAL_PREVIEW_UNAVAILABLE", 503) from None
    except (ValidationError, KeyError, TypeError, ValueError, OverflowError):
        raise _error("FINANCIAL_CONFIGURATION_INVALID", 503) from None


class _ReadCursor:
    def __init__(self, collection, query, projection=None):
        self.collection, self.query, self.projection = collection, query, projection
        self.maximum = None

    def limit(self, value):
        self.maximum = value
        return self

    async def to_list(self, length):
        maximum = min(length, self.maximum) if self.maximum is not None else length
        if type(maximum) is not int or not 1 <= maximum <= 301:
            raise _error("FINANCIAL_CONFIGURATION_INVALID", 503)
        # Size is checked in Mongo before the document crosses the wire. Unknown
        # tariff fields remain present for the existing strict model to reject.
        rows = await self.collection.raw.aggregate([
            {"$match": self.query}, {"$limit": maximum},
            {"$project": {"_id": 0, "document": {"$cond": [
                {"$lte": [{"$bsonSize": "$$ROOT"}, self.collection.size]}, "$$ROOT", None]}}},
        ], maxTimeMS=MAX_TIME_MS).to_list(maximum)
        output = []
        for row in rows:
            doc = row.get("document")
            if not isinstance(doc, dict):
                raise _error("FINANCIAL_CONFIGURATION_INVALID", 503)
            projection = self.projection
            if projection:
                include = [key for key, value in projection.items() if value and key != "_id"]
                if include:
                    doc = {key: value for key, value in doc.items()
                           if key in include or key == "_id" and projection.get("_id", 1)}
                else:
                    doc = {key: value for key, value in doc.items() if projection.get(key, 1)}
            output.append(doc)
        return output


class _ReadCollection:
    def __init__(self, raw, size=65536):
        self.raw, self.size = raw, size

    def find(self, query, projection=None, session=None):
        return _ReadCursor(self, query, projection)

    async def find_one(self, query, projection=None, session=None):
        rows = await self.find(query, projection).limit(2).to_list(2)
        if len(rows) > 1:
            raise _error("FINANCIAL_CONFIGURATION_INVALID", 503)
        return rows[0] if rows else None


class _ReadDatabase:
    """Capability-limited adapter also bounds existing L3/L5A read helpers."""
    SIZES = {"users": 8192, "restaurants": 16384, "order_operation_settings": 4096,
             "restaurant_tariff_versions": 131072, "delivery_zones": 65536,
             "orders": 65536, "order_custody_events": 16384, "order_incidents": 8192,
             "order_operations": 65536}

    def __init__(self, database):
        self.raw = database

    def get_collection(self, name, **options):
        if name not in self.SIZES:
            raise _error("FINANCIAL_CONFIGURATION_INVALID", 503)
        return _ReadCollection(self.raw.get_collection(name), self.SIZES[name])

    def __getattr__(self, name):
        return self.get_collection(name)


class _FrozenCursor:
    def __init__(self, rows):
        self.rows = rows

    def limit(self, maximum):
        self.rows = self.rows[:maximum]
        return self

    async def to_list(self, maximum):
        return self.rows[:maximum]


class _FrozenConfiguration:
    """The exact validated grid/zones are consumed by the unchanged L3 helpers."""
    def __init__(self, grid, zones, restaurant_id):
        self.grid, self.zones, self.restaurant_id = grid, zones, restaurant_id
        self.order_operation_settings = self.restaurant_tariff_versions = self.delivery_zones = self

    async def find_one(self, query):
        if query != {"_id": "order-finance-v1"}:
            raise _error("FINANCIAL_CONFIGURATION_INVALID", 503)
        return {"enabled": True}

    def find(self, query, projection=None, session=None):
        if query == {"is_active": True, "restaurant_id": self.restaurant_id}:
            return _FrozenCursor(self.zones)
        if query == {"restaurant_id": self.restaurant_id, "version": self.grid.version}:
            return _FrozenCursor([self.grid.model_dump(mode="json")])
        raise _error("FINANCIAL_CONFIGURATION_INVALID", 503)


class OrderFinancePreviewService:
    def __init__(self, database, *, signing_key=None):
        self.db = _ReadDatabase(database)
        self.creation = OrderCreationService(self.db)
        self.signing_key = signing_key

    def _fingerprint_key(self):
        key = self.signing_key
        if isinstance(key, str):
            key = key.encode("utf-8")
        if not isinstance(key, bytes) or not key.strip() or len(key) > 4096:
            raise _error("FINANCIAL_PREVIEW_KEY_UNAVAILABLE", 503)
        return hmac.new(key, b"pd-finance-preview-v1-key", hashlib.sha256).digest()

    async def authenticate(self, signed_actor):
        """Keep signed role/tenant context for every later authoritative recheck."""
        async with _bounded():
            _identifier(_identity(signed_actor))
            await self.creation._actor(signed_actor, signed_actor.get("restaurant_id"))
            return signed_actor

    async def _scope(self, actor, restaurant_id):
        restaurant_id = _identifier(restaurant_id)
        user = await self.creation._actor(actor, restaurant_id)
        _identifier(_identity(user))
        restaurant = await self.db.restaurants.find_one({"id": restaurant_id},
            {"id": 1, "name": 1, "account_disabled": 1, "is_active": 1, "accepting_orders": 1})
        if restaurant and any(name in restaurant and type(restaurant[name]) is not bool
                for name in ("account_disabled", "is_active", "accepting_orders")):
            raise _error("RESTAURANT_INVALID")
        rejection = self.creation._restaurant_rejection(restaurant)
        if rejection:
            raise rejection
        return user

    async def _flags(self):
        flags = {}
        for name in ("finance", "create", "remake"):
            row = await self.db.order_operation_settings.find_one({"_id": f"order-{name}-v1"},
                                                                   {"enabled": 1, "_id": 0})
            if row is not None and type(row.get("enabled")) is not bool:
                raise _error("CAPABILITIES_INVALID", 503)
            flags[name] = row is not None and row["enabled"]
        return flags

    async def capabilities(self, restaurant_id, actor):
        async with _bounded():
            user = await self._scope(actor, restaurant_id)
            flags = await self._flags()
            await self._scope(actor, restaurant_id)
            return FinanceCapabilities(actor_id=_identity(user), restaurant_id=restaurant_id,
                finance_enabled=flags["finance"],
                create_quote_enabled=user["role"] == "admin" and flags["finance"] and flags["create"],
                remake_quote_enabled=flags["finance"] and flags["remake"]).model_dump(mode="json")

    async def _grids(self, restaurant_id):
        rows = await self.db.restaurant_tariff_versions.find({"restaurant_id": restaurant_id}, {"_id": 0}) \
            .limit(MAX_TARIFFS + 1).to_list(MAX_TARIFFS + 1)
        if len(rows) > MAX_TARIFFS:
            raise _error("FINANCIAL_GRID_LIMIT", 503)
        grids, versions = [], set()
        for row in rows:
            try:
                grid = RestaurantTariffVersion.model_validate(row)
            except ValidationError:
                raise _error("FINANCIAL_GRID_INVALID") from None
            if grid.restaurant_id != restaurant_id or grid.version in versions:
                raise _error("FINANCIAL_GRID_INVALID")
            versions.add(grid.version)
            if grid.approved:
                if (not grid.zones or any(rule.restaurant_transport_bani is None
                        or rule.courier_remuneration_bani is None for rule in grid.zones.values())):
                    raise _error("FINANCIAL_GRID_INCOMPLETE")
                grids.append(grid)
        return sorted(grids, key=lambda grid: grid.version)

    async def tariffs(self, restaurant_id, actor):
        async with _bounded():
            user = await self._scope(actor, restaurant_id)
            if not (await self._flags())["finance"]:
                raise _error("FINANCIAL_NOT_ENABLED", 503)
            grids = await self._grids(restaurant_id)
            await self._scope(actor, restaurant_id)
            return FinanceTariffs(actor_id=_identity(user), restaurant_id=restaurant_id,
                tariffs=[{"version": grid.version, "currency": grid.currency,
                          "zone_ids": sorted(grid.zones)} for grid in grids]).model_dump(mode="json")

    async def _configuration(self, restaurant_id, request):
        if request.basis != "zone":
            raise _error("FINANCIAL_PREVIEW_OUTSIDE_UNAVAILABLE")
        grids = await self._grids(restaurant_id)
        grid = next((value for value in grids if value.version == request.tariff_version), None)
        if grid is None:
            raise _error("FINANCIAL_GRID_UNAVAILABLE")
        zones = await self.db.delivery_zones.find({"is_active": True, "restaurant_id": restaurant_id},
            {"id": 1, "name": 1, "sector": 1, "zone_level": 1, "polygon": 1, "_id": 0}) \
            .limit(MAX_ZONES + 1).to_list(MAX_ZONES + 1)
        if not zones or len(zones) > MAX_ZONES:
            raise _error("FINANCIAL_ZONE_UNVERIFIED")
        seen = set()
        for zone in zones:
            try:
                identity = _identifier(zone.get("id"))
                if identity in seen:
                    raise ValueError()
                seen.add(identity)
                name = zone.get("name")
                if (not isinstance(name, str) or not 1 <= len(name) <= 160 or name.strip() != name
                        or any(ord(c) < 32 or ord(c) == 127 for c in name)):
                    raise ValueError()
                sector = zone.get("sector")
                if sector is not None and (not isinstance(sector, str) or len(sector) > 80
                        or sector.strip() != sector or any(ord(c) < 32 or ord(c) == 127 for c in sector)):
                    raise ValueError()
                level = zone.get("zone_level")
                if level is not None and (type(level) not in (int, Int64) or not 0 <= level <= 50):
                    raise ValueError()
                coords = zone.get("polygon")
                if not isinstance(coords, list) or not 3 <= len(coords) <= MAX_POINTS:
                    raise ValueError()
                for point in coords:
                    if not isinstance(point, dict) or set(point) != {"lat", "lng"}:
                        raise ValueError()
                    for key, limit in (("lat", 90), ("lng", 180)):
                        value = point[key]
                        if type(value) not in (int, Int64, float) or not math.isfinite(value) or not -limit <= value <= limit:
                            raise ValueError()
            except (CreationError, ValueError, TypeError, KeyError):
                raise _error("FINANCIAL_ZONE_UNVERIFIED") from None
        return _FrozenConfiguration(grid, zones, restaurant_id)

    async def _quote_material(self, kind, command, draft, user, parent=None):
        frozen = await self._configuration(command.order.restaurant_id, command.financial)
        # Reuse the area/contains policy and all L3 amount/rule validation.
        zone = await OrderCreationService._zone(type("ZoneReader", (), {"db": frozen})(), command.order, None)
        snapshot = await quote_at_admission(frozen, command, user, PREVIEW_OPERATION, zone)
        stable = {key: value for key, value in snapshot.items()
                  if key not in {"snapshot_at", "snapshot_digest", "operation_ref"}}
        binding = {"contract_version": 1, "kind": kind, "actor_id": _identity(user),
            "actor_role": user["role"], "restaurant_id": command.order.restaurant_id,
            "draft": draft, "parent": {key: parent.get(key) for key in (
                "id", "restaurant_id", "order_version", "status", "source", "customer_name", "customer_phone",
                "customer_address", "customer_latitude", "customer_longitude")} if parent else None, "zone_proof": zone,
            "grid": frozen.grid.model_dump(mode="json"), "quote": stable}
        fingerprint = hmac.new(self._fingerprint_key(), json.dumps(binding, sort_keys=True,
            separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode(), hashlib.sha256).hexdigest()
        return snapshot, fingerprint

    async def _quote(self, kind, command, draft, user, parent=None):
        snapshot, fingerprint = await self._quote_material(kind, command, draft, user, parent)
        return self._public_quote(kind, snapshot, fingerprint, user, parent)

    @staticmethod
    def _public_quote(kind, snapshot, fingerprint, user, parent=None):
        stable = {key: value for key, value in snapshot.items()
                  if key not in {"snapshot_at", "snapshot_digest", "operation_ref"}}
        fields = FinancePreview.model_fields
        values = {key: value for key, value in stable.items() if key in fields}
        values.update(kind=kind, actor_id=_identity(user), quote_fingerprint=fingerprint,
            parent_order_id=parent["id"] if parent else None,
            parent_order_version=int(parent["order_version"]) if parent else None)
        if user["role"] == "admin":
            values["courier_remuneration_bani"] = snapshot["courier_remuneration_bani"]
            return AdminFinancePreview(**values).model_dump(mode="json")
        return FinancePreview(**values).model_dump(mode="json")

    async def prepare_create_confirmation(self, command, actor, operation_ref):
        """Sample once for both HMAC and admission; this is not a config CAS.

        The bounded read adapter is deliberately outside the transaction. Never
        re-fetch pricing after verification or use it for admitted recovery.
        """
        async with _bounded():
            self._fingerprint_key()
            request = CreateFinancePreview(order=command.order, financial=command.financial)
            user = await self._scope(actor, request.order.restaurant_id)
            if user["role"] != "admin":
                raise _error("NOT_AUTHORIZED", 403)
            flags = await self._flags()
            if not flags["finance"] or not flags["create"]:
                raise _error("FINANCIAL_CREATE_NOT_ENABLED", 503)
            snapshot, fingerprint = await self._quote_material(
                "create", command, request.model_dump(mode="json"), user)
            await self._scope(actor, request.order.restaurant_id)
            snapshot.update(operation_ref=operation_ref, snapshot_at=datetime.now(timezone.utc).isoformat())
            snapshot.pop("snapshot_digest")
            snapshot["snapshot_digest"] = _digest(snapshot)
            return validate_snapshot(snapshot).model_dump(mode="json"), fingerprint

    async def quote_create(self, request, actor):
        async with _bounded():
            request = CreateFinancePreview.model_validate(request.model_dump(mode="python"))
            user = await self._scope(actor, request.order.restaurant_id)
            if user["role"] != "admin":
                raise _error("NOT_AUTHORIZED", 403)
            flags = await self._flags()
            if not flags["finance"] or not flags["create"]:
                raise _error("FINANCIAL_CREATE_NOT_ENABLED", 503)
            command = CreateOrderCommand(client_operation_id=PREVIEW_OPERATION, **request.model_dump(mode="python"))
            result = await self._quote("create", command, request.model_dump(mode="json"), user)
            await self._scope(actor, request.order.restaurant_id)
            return result

    async def quote_remake(self, parent_id, request, actor):
        async with _bounded():
            request = RemakeFinancePreview.model_validate(request.model_dump(mode="python"))
            command = RemakeCommand(client_operation_id=PREVIEW_OPERATION, **request.model_dump(mode="python"))
            parent, child, user, snapshot, fingerprint = await self._remake_material(parent_id, command, actor)
            return self._public_quote("remake", snapshot, fingerprint, user, parent)

    async def _remake_material(self, parent_id, command, actor):
        parent_id = _identifier(parent_id)
        user = await self.creation._actor(actor, actor.get("restaurant_id"))
        query = {"id": parent_id}
        if user["role"] == "restaurant":
            query["restaurant_id"] = user["restaurant_id"]
        parent = await self.db.orders.find_one(query,
            {**{field: 1 for field in PARENT_FIELDS + CUSTODY_PARENT_FIELDS}, "_id": 0})
        if parent is None:
            raise _error("ORDER_NOT_FOUND", 404)
        user = await self._scope(actor, parent.get("restaurant_id"))
        flags = await self._flags()
        if not flags["finance"] or not flags["remake"]:
            raise _error("FINANCIAL_REMAKE_NOT_ENABLED", 503)
        _policy(command)
        _validate_parent(parent, command)
        await OrderRemakeService(self.db)._custody(parent)
        child = _child_command(parent, command)
        request = RemakeFinancePreview.model_validate(command.model_dump(mode="python",
            exclude={"client_operation_id", "quote_confirmation"}))
        snapshot, fingerprint = await self._quote_material("remake", child, request.model_dump(mode="json"), user, parent)
        await self._scope(actor, parent["restaurant_id"])
        return parent, child, user, snapshot, fingerprint

    async def prepare_remake_confirmation(self, parent_id, command, actor, operation_ref):
        """One sampled material for confirmation and immutable admission, not config CAS."""
        async with _bounded():
            self._fingerprint_key()
            parent, child, user, snapshot, fingerprint = await self._remake_material(parent_id, command, actor)
            snapshot.update(operation_ref=operation_ref, snapshot_at=datetime.now(timezone.utc).isoformat())
            snapshot.pop("snapshot_digest")
            snapshot["snapshot_digest"] = _digest(snapshot)
            return PreparedRemakeConfirmation(_parent_snapshot(parent), child,
                validate_snapshot(snapshot).model_dump(mode="json"), fingerprint)
