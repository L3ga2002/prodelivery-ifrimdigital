from fastapi import APIRouter, HTTPException, Depends, Query, UploadFile, File, Body, Response
from datetime import datetime, timedelta, timezone
import uuid
import secrets
from database import db
from auth import hash_password, verify_password, get_current_user
from models.driver import (
    DriverAvatarModeration,
    DriverCreate,
    DriverEmailVerification,
    DriverProfileUpdate,
    DriverSelfProfileUpdate,
    DriverDisableUpdate,
    DriverRankingUpdate,
    DriverStatusUpdate,
)
from utils.driver_ranking import build_driver_ranking_payload
from utils.email_service import EmailDeliveryError, send_driver_verification_email
from utils.driver_ranking import ROMANIA_TZ
from utils.avatar_storage import process_driver_avatar

router = APIRouter(prefix="/drivers", tags=["drivers"])
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
ACTIVE_DRIVER_STATUSES = {"active", "delivery", "break"}


def _normalise_email(email: str) -> str:
    return email.strip().lower()


def _generate_verification_code() -> str:
    return f"{secrets.randbelow(900000) + 100000}"


def _generate_initial_password() -> str:
    return secrets.token_urlsafe(12)


def _split_driver_name(name: str | None) -> tuple[str, str]:
    parts = (name or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _validate_ro_phone(phone: str) -> str:
    value = phone.strip().replace(" ", "")
    allowed = value.startswith("+40") and len(value) == 12 and value[1:].isdigit()
    local = value.startswith("07") and len(value) == 10 and value.isdigit()
    if not (allowed or local):
        raise HTTPException(status_code=400, detail="Numărul de telefon trebuie să fie 07xxxxxxxx sau +407xxxxxxxx")
    return value


def _validate_birth_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value).date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Data nașterii trebuie să fie validă") from exc
    today = datetime.now(timezone.utc).date()
    age = today.year - parsed.year - ((today.month, today.day) < (parsed.month, parsed.day))
    if age < 16 or age > 90:
        raise HTTPException(status_code=400, detail="Vârsta livratorului nu este validă")
    return parsed.isoformat()


def _validate_cnp(cnp: str | None) -> str | None:
    value = (cnp or "").strip()
    if not value:
        return None
    if not (len(value) == 13 and value.isdigit()):
        raise HTTPException(status_code=400, detail="CNP-ul trebuie să aibă 13 cifre")
    return value


def _current_week_and_day() -> tuple[str, str, str]:
    now = datetime.now(ROMANIA_TZ)
    monday = now - timedelta(days=now.weekday())
    return monday.date().isoformat(), DAYS[now.weekday()], f"{now.hour:02d}:00"


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _status_label(status: str) -> str:
    return {
        "active": "Activ",
        "delivery": "În livrare",
        "break": "În pauză",
        "offline": "Offline",
    }.get(status, status)


async def _log_driver_audit(driver_id: str, current_user: dict, action: str, changes: dict | None = None) -> None:
    await db.audit_logs.insert_one({
        "id": str(uuid.uuid4()),
        "entity_type": "driver",
        "entity_id": driver_id,
        "action": action,
        "changes": changes or {},
        "performed_by": current_user.get("user_id"),
        "performed_by_email": current_user.get("email"),
        "performed_by_role": current_user.get("role"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


async def _ensure_admin_or_self(driver_id: str, current_user: dict) -> dict:
    driver = await db.drivers.find_one({"id": driver_id}, {"_id": 0})
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    if current_user["role"] == "admin":
        return driver
    if current_user["role"] == "driver" and current_user.get("driver_id") == driver_id:
        return driver
    raise HTTPException(status_code=403, detail="Not authorized")


async def _attach_user_contact(driver: dict) -> dict:
    user = await db.users.find_one({"id": driver.get("user_id")}, {"_id": 0})
    if not user:
        user = {}
    first_name, last_name = _split_driver_name(driver.get("name") or user.get("name"))
    return {
        **driver,
        "email": driver.get("email") or user.get("email"),
        "phone": driver.get("phone") or user.get("phone") or "",
        "name": driver.get("name") or user.get("name") or "",
        "first_name": driver.get("first_name") or user.get("first_name") or first_name,
        "last_name": driver.get("last_name") or user.get("last_name") or last_name,
        "birth_date": driver.get("birth_date") or user.get("birth_date"),
        "gender": driver.get("gender") or user.get("gender"),
        "cnp": driver.get("cnp") or user.get("cnp"),
        "phone_verified": bool(driver.get("phone_verified") or user.get("phone_verified")),
    }


async def _attach_today_schedule_state(driver: dict) -> dict:
    week_start, day_key, current_hour = _current_week_and_day()
    schedule = await db.schedules.find_one(
        {"driver_id": driver["id"], "week_start": week_start},
        {"_id": 0},
    )
    today_slots = (schedule or {}).get("slots", {}).get(day_key, [])
    is_scheduled_today = len(today_slots) > 0
    is_on_shift_now = any(slot.get("start") == current_hour for slot in today_slots)
    now_utc = datetime.now(timezone.utc)
    break_until = _parse_iso_datetime(driver.get("break_until"))
    break_remaining_seconds = max(int((break_until - now_utc).total_seconds()), 0) if break_until else 0
    raw_status = driver.get("driver_status")
    if driver.get("current_order_id"):
        operational_status = "delivery"
    elif raw_status == "break" and break_remaining_seconds > 0:
        operational_status = "break"
    elif raw_status == "active":
        operational_status = "active"
    elif driver.get("is_active"):
        operational_status = "active"
    else:
        operational_status = "offline"
    return {
        **driver,
        "vehicle_type": driver.get("vehicle_type", "scooter"),
        "email_verified": driver.get("email_verified", True),
        "schedule_today_hours": len(today_slots),
        "is_scheduled_today": is_scheduled_today,
        "is_on_shift_now": is_on_shift_now,
        "operational_status": operational_status,
        "operational_status_label": _status_label(operational_status),
        "break_remaining_seconds": break_remaining_seconds,
    }


@router.patch("/{driver_id}/self-profile")
async def update_driver_self_profile(driver_id: str, data: DriverSelfProfileUpdate, current_user: dict = Depends(get_current_user)):
    driver = await _ensure_admin_or_self(driver_id, current_user)
    if current_user["role"] != "driver" and current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    normalized_email = _normalise_email(str(data.email))
    normalized_phone = _validate_ro_phone(data.phone)
    birth_date = _validate_birth_date(data.birth_date)
    cnp = _validate_cnp(data.cnp)
    first_name = data.first_name.strip()
    last_name = data.last_name.strip()
    if len(first_name) < 2 or len(last_name) < 2:
        raise HTTPException(status_code=400, detail="Numele și prenumele sunt obligatorii")

    duplicate = await db.users.find_one({"email": normalized_email, "id": {"$ne": driver.get("user_id")}}, {"_id": 0})
    if duplicate:
        raise HTTPException(status_code=400, detail="Emailul este deja folosit de alt cont")

    full_name = f"{first_name} {last_name}".strip()
    email_changed = normalized_email != (driver.get("email") or "")
    phone_changed = normalized_phone != (driver.get("phone") or "")
    update = {
        "first_name": first_name,
        "last_name": last_name,
        "name": full_name,
        "birth_date": birth_date,
        "gender": data.gender,
        "cnp": cnp,
        "phone": normalized_phone,
        "email": normalized_email,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if phone_changed:
        update["phone_verified"] = False
        update["phone_verification_status"] = "sms_not_configured"
    if email_changed:
        update["email_verified"] = False

    await db.drivers.update_one({"id": driver_id}, {"$set": update})
    await db.users.update_one({"id": driver["user_id"]}, {"$set": update})
    if email_changed:
        try:
            await _create_and_send_verification(driver_id, driver["user_id"], normalized_email, full_name)
        except EmailDeliveryError as exc:
            await db.drivers.update_one({"id": driver_id}, {"$set": {"email_verification_delivery_status": "failed"}})
            await db.users.update_one({"id": driver["user_id"]}, {"$set": {"email_verification_delivery_status": "failed"}})
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    await _log_driver_audit(driver_id, current_user, "driver_self_profile_updated", {
        "email_changed": email_changed,
        "phone_changed": phone_changed,
        "identity_fields_changed": True,
    })
    updated_driver = await _attach_user_contact(await db.drivers.find_one({"id": driver_id}, {"_id": 0}))
    return {"message": "Profil actualizat", "driver": updated_driver, "email_verification_sent": email_changed}


async def _create_and_send_verification(driver_id: str, user_id: str, email: str, name: str) -> dict:
    code = _generate_verification_code()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    payload = {
        "email_verification_code_hash": hash_password(code),
        "email_verification_expires_at": expires_at.isoformat(),
        "email_verified": False,
        "email_verification_sent_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.update_one({"id": user_id}, {"$set": payload})
    await db.drivers.update_one({"id": driver_id}, {"$set": payload})
    try:
        email_response = await send_driver_verification_email(email, name, code)
        delivery = {"status": "sent", "email_id": email_response.get("id") if isinstance(email_response, dict) else None}
    except EmailDeliveryError as exc:
        if exc.reason != "test_domain_restricted":
            raise
        delivery = {
            "status": "test_domain_restricted",
            "message": str(exc),
            "verification_code": code,
            "expires_at": expires_at.isoformat(),
        }
    await db.users.update_one({"id": user_id}, {"$set": {"email_verification_delivery_status": delivery["status"]}})
    await db.drivers.update_one({"id": driver_id}, {"$set": {"email_verification_delivery_status": delivery["status"]}})
    return delivery


@router.get("")
async def get_drivers(current_user: dict = Depends(get_current_user)):
    drivers = await db.drivers.find({"account_disabled": {"$ne": True}}, {"_id": 0}).to_list(100)
    enriched_drivers = []
    for driver in drivers:
        ranking = await build_driver_ranking_payload(db, driver)
        schedule_state = await _attach_today_schedule_state(driver)
        enriched_drivers.append({**schedule_state, **ranking})
    return enriched_drivers


@router.get("/rankings")
async def get_driver_rankings(current_user: dict = Depends(get_current_user)):
    drivers = await db.drivers.find({"account_disabled": {"$ne": True}}, {"_id": 0}).to_list(100)
    rankings = []
    for driver in drivers:
        ranking = await build_driver_ranking_payload(db, driver)
        rankings.append({
            "driver_id": driver["id"],
            "driver_name": driver["name"],
            **ranking,
        })
    return sorted(rankings, key=lambda item: item["ranking_score"], reverse=True)


@router.get("/ranking/me")
async def get_my_ranking(current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "driver":
        raise HTTPException(status_code=403, detail="Driver only")

    driver = await db.drivers.find_one({"user_id": current_user["user_id"]}, {"_id": 0})
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    ranking = await build_driver_ranking_payload(db, driver)
    return {"driver_id": driver["id"], "driver_name": driver["name"], **ranking}


@router.get("/{driver_id}")
async def get_driver(driver_id: str, current_user: dict = Depends(get_current_user)):
    driver = await db.drivers.find_one({"id": driver_id}, {"_id": 0})
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    return driver


@router.get("/{driver_id}/dashboard")
async def get_driver_dashboard(driver_id: str, current_user: dict = Depends(get_current_user)):
    driver = await _attach_user_contact(await _ensure_admin_or_self(driver_id, current_user))
    ranking = await build_driver_ranking_payload(db, driver)
    schedule_state = await _attach_today_schedule_state(driver)
    schedules = await db.schedules.find({"driver_id": driver_id}, {"_id": 0}).sort("week_start", -1).to_list(24)
    orders = await db.orders.find({"driver_id": driver_id}, {"_id": 0}).sort("created_at", -1).to_list(25)
    avatars = await db.driver_avatars.find({"driver_id": driver_id, "is_deleted": False}, {"_id": 0}).sort("uploaded_at", -1).to_list(20)
    audit_logs = []
    if current_user["role"] == "admin":
        audit_logs = await db.audit_logs.find({"entity_type": "driver", "entity_id": driver_id}, {"_id": 0}).sort("created_at", -1).to_list(30)
    return {
        "driver": {**schedule_state, **ranking},
        "schedules": schedules,
        "recent_orders": orders,
        "avatars": avatars,
        "audit_logs": audit_logs,
    }


@router.patch("/{driver_id}/profile")
async def update_driver_profile(driver_id: str, data: DriverProfileUpdate, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    driver = await db.drivers.find_one({"id": driver_id}, {"_id": 0})
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")

    normalized_email = _normalise_email(str(data.email))
    duplicate = await db.users.find_one({"email": normalized_email, "id": {"$ne": driver.get("user_id")}}, {"_id": 0})
    if duplicate:
        raise HTTPException(status_code=400, detail="Emailul este deja folosit de alt cont")
    if data.new_password and len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="Parola nouă trebuie să aibă minimum 6 caractere")

    email_changed = normalized_email != driver.get("email")
    driver_update = {
        "name": data.name.strip(),
        "phone": data.phone.strip(),
        "email": normalized_email,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    user_update = {
        "name": data.name.strip(),
        "phone": data.phone.strip(),
        "email": normalized_email,
    }
    if email_changed:
        driver_update["email_verified"] = False
        user_update["email_verified"] = False
    if data.new_password:
        user_update["password_hash"] = hash_password(data.new_password)
        user_update["password_updated_at"] = datetime.now(timezone.utc).isoformat()
        user_update["password_updated_by"] = current_user.get("user_id")

    await db.drivers.update_one({"id": driver_id}, {"$set": driver_update})
    await db.users.update_one({"id": driver["user_id"]}, {"$set": user_update})
    await _log_driver_audit(driver_id, current_user, "driver_profile_updated", {
        "name_changed": driver.get("name") != data.name.strip(),
        "phone_changed": driver.get("phone") != data.phone.strip(),
        "email_changed": email_changed,
        "password_changed": bool(data.new_password),
    })
    updated_driver = await db.drivers.find_one({"id": driver_id}, {"_id": 0})
    return {"message": "Profil livrator actualizat", "driver": updated_driver}


@router.patch("/{driver_id}/ranking")
async def update_driver_ranking(driver_id: str, data: DriverRankingUpdate, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    driver = await db.drivers.find_one({"id": driver_id}, {"_id": 0})
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    update = {
        "manual_rank_note": (data.manual_rank_note or "").strip() or None,
        "manual_rank_updated_at": datetime.now(timezone.utc).isoformat(),
        "manual_rank_updated_by": current_user.get("user_id"),
    }
    if data.manual_ranking_score is None:
        update["manual_ranking_score"] = None
    else:
        update["manual_ranking_score"] = round(max(0, min(float(data.manual_ranking_score), 100)), 1)
    await db.drivers.update_one({"id": driver_id}, {"$set": update})
    await _log_driver_audit(driver_id, current_user, "driver_rank_updated", update)
    updated_driver = await db.drivers.find_one({"id": driver_id}, {"_id": 0})
    ranking = await build_driver_ranking_payload(db, updated_driver)
    return {"message": "Scor livrator actualizat", "driver_id": driver_id, **ranking}


@router.post("")
async def create_driver(data: DriverCreate, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    normalized_email = _normalise_email(str(data.email))
    existing = await db.users.find_one({"email": normalized_email}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=400, detail="Email deja înregistrat")

    user_id = str(uuid.uuid4())
    driver_id = str(uuid.uuid4())
    initial_password = _generate_initial_password()

    user_doc = {
        "id": user_id,
        "email": normalized_email,
        "name": data.name,
        "role": "driver",
        "phone": data.phone,
        "vehicle_type": data.vehicle_type,
        "email_verified": False,
        "driver_status": "offline",
        "password_hash": hash_password(initial_password),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.users.insert_one(user_doc)

    driver_doc = {
        "id": driver_id,
        "user_id": user_id,
        "name": data.name,
        "email": normalized_email,
        "phone": data.phone,
        "vehicle_type": data.vehicle_type,
        "email_verified": False,
        "is_active": False,
        "driver_status": "offline",
        "latitude": 46.567 + (hash(data.name) % 100) / 10000,
        "longitude": 26.913 + (hash(data.phone) % 100) / 10000,
        "current_order_id": None,
        "total_deliveries": 0,
        "total_earnings": 0,
        "punctuality_rate": 0.85,
        "joined_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.drivers.insert_one(driver_doc)

    email_delivery = {"status": "not_sent"}
    try:
        email_delivery = await _create_and_send_verification(driver_id, user_id, normalized_email, data.name)
    except EmailDeliveryError as exc:
        email_delivery = {"status": "failed", "message": str(exc)}

    return {
        "message": "Driver created",
        "driver_id": driver_id,
        "password": initial_password,
        "email_delivery": email_delivery,
    }


@router.post("/{driver_id}/avatar")
async def upload_driver_avatar(driver_id: str, file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    driver = await _ensure_admin_or_self(driver_id, current_user)
    avatar_file = await process_driver_avatar(file)
    is_admin_upload = current_user["role"] == "admin"
    status = "approved" if is_admin_upload else "pending"
    now = datetime.now(timezone.utc).isoformat()
    avatar_doc = {
        "id": avatar_file["avatar_id"],
        "driver_id": driver_id,
        "user_id": driver.get("user_id"),
        "status": status,
        "file_path": avatar_file["file_path"],
        "content_type": avatar_file["content_type"],
        "size": avatar_file["size"],
        "uploaded_by": current_user.get("user_id"),
        "uploaded_by_role": current_user.get("role"),
        "uploaded_at": now,
        "approved_at": now if is_admin_upload else None,
        "approved_by": current_user.get("user_id") if is_admin_upload else None,
        "is_active": is_admin_upload,
        "is_deleted": False,
        "image_url": f"/api/drivers/{driver_id}/avatars/{avatar_file['avatar_id']}/image",
    }
    if is_admin_upload:
        await db.driver_avatars.update_many({"driver_id": driver_id}, {"$set": {"is_active": False}})
    await db.driver_avatars.insert_one(avatar_doc)
    avatar_doc.pop("_id", None)
    if is_admin_upload:
        avatar_update = {
            "active_avatar_id": avatar_doc["id"],
            "avatar_url": avatar_doc["image_url"],
            "avatar_status": "approved",
        }
        await db.drivers.update_one({"id": driver_id}, {"$set": avatar_update})
        await db.users.update_one({"id": driver.get("user_id")}, {"$set": avatar_update})
    else:
        await db.drivers.update_one({"id": driver_id}, {"$set": {"avatar_status": "pending"}})
    await _log_driver_audit(driver_id, current_user, "driver_avatar_uploaded", {"status": status, "avatar_id": avatar_doc["id"]})
    avatar_doc.pop("file_path", None)
    return {"message": "Poza a fost încărcată" if is_admin_upload else "Poza a fost trimisă la aprobare", "avatar": avatar_doc}


@router.patch("/{driver_id}/disable")
async def disable_driver_account(driver_id: str, data: DriverDisableUpdate | None = Body(default=None), current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    driver = await db.drivers.find_one({"id": driver_id}, {"_id": 0})
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    active_orders = await db.orders.count_documents({"driver_id": driver_id, "status": {"$nin": ["DELIVERED", "CANCELLED"]}})
    if active_orders > 0:
        raise HTTPException(status_code=409, detail="Livratorul are comenzi active. Reasignează sau finalizează comenzile înainte de dezactivare.")
    now = datetime.now(timezone.utc).isoformat()
    update = {
        "account_disabled": True,
        "account_disabled_at": now,
        "account_disabled_by": current_user.get("user_id"),
        "account_disabled_reason": (data.reason if data else None) or "Dezactivat manual de admin",
        "driver_status": "offline",
        "is_active": False,
        "break_started_at": None,
        "break_until": None,
    }
    await db.drivers.update_one({"id": driver_id}, {"$set": update})
    await db.users.update_one({"id": driver.get("user_id")}, {"$set": update})
    await _log_driver_audit(driver_id, current_user, "driver_account_disabled", update)
    return {"message": "Cont livrator dezactivat", "driver_id": driver_id}


@router.patch("/{driver_id}/avatars/{avatar_id}")
async def moderate_driver_avatar(driver_id: str, avatar_id: str, data: DriverAvatarModeration, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    driver = await db.drivers.find_one({"id": driver_id}, {"_id": 0})
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    avatar = await db.driver_avatars.find_one({"id": avatar_id, "driver_id": driver_id, "is_deleted": False}, {"_id": 0})
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")
    now = datetime.now(timezone.utc).isoformat()
    if data.action == "approve":
        await db.driver_avatars.update_many({"driver_id": driver_id}, {"$set": {"is_active": False}})
        image_url = f"/api/drivers/{driver_id}/avatars/{avatar_id}/image"
        await db.driver_avatars.update_one({"id": avatar_id}, {"$set": {"status": "approved", "is_active": True, "approved_at": now, "approved_by": current_user.get("user_id"), "moderation_note": data.note}})
        avatar_update = {"active_avatar_id": avatar_id, "avatar_url": image_url, "avatar_status": "approved"}
        await db.drivers.update_one({"id": driver_id}, {"$set": avatar_update})
        await db.users.update_one({"id": driver.get("user_id")}, {"$set": avatar_update})
    else:
        await db.driver_avatars.update_one({"id": avatar_id}, {"$set": {"status": "rejected", "is_active": False, "rejected_at": now, "rejected_by": current_user.get("user_id"), "moderation_note": data.note}})
    await _log_driver_audit(driver_id, current_user, f"driver_avatar_{data.action}ed", {"avatar_id": avatar_id, "note": data.note})
    return {"message": "Avatar aprobat" if data.action == "approve" else "Avatar respins"}


@router.get("/{driver_id}/avatars/{avatar_id}/image")
async def get_driver_avatar_image(driver_id: str, avatar_id: str):
    avatar = await db.driver_avatars.find_one({"id": avatar_id, "driver_id": driver_id, "is_deleted": False}, {"_id": 0})
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")
    try:
        data = open(avatar["file_path"], "rb").read()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Avatar image missing") from exc
    return Response(content=data, media_type=avatar.get("content_type", "image/webp"))


@router.delete("/{driver_id}")
async def delete_driver(
    driver_id: str,
    confirm_delete: bool = Query(default=False),
    current_user: dict = Depends(get_current_user),
):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    if not confirm_delete:
        raise HTTPException(status_code=409, detail="Confirmă explicit ștergerea livratorului")
    driver = await db.drivers.find_one({"id": driver_id}, {"_id": 0})
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    active_orders = await db.orders.count_documents({
        "driver_id": driver_id,
        "status": {"$nin": ["DELIVERED", "CANCELLED"]},
    })
    if active_orders > 0:
        raise HTTPException(status_code=409, detail="Livratorul are comenzi active. Reasignează sau finalizează comenzile înainte de ștergere.")

    touched_emergency_slots = await db.emergency_slots.find({"claimed_by": driver_id}, {"_id": 0}).to_list(200)
    for slot in touched_emergency_slots:
        claimed_by = [item for item in slot.get("claimed_by", []) if item != driver_id]
        claimed_names = [item for item in slot.get("claimed_names", []) if item != driver.get("name")]
        remaining = min(int(slot.get("total_spots", 0)), int(slot.get("remaining_spots", 0)) + 1)
        await db.emergency_slots.update_one(
            {"id": slot["id"]},
            {"$set": {"claimed_by": claimed_by, "claimed_names": claimed_names, "remaining_spots": remaining}},
        )

    schedules_result = await db.schedules.delete_many({"driver_id": driver_id})
    await db.orders.update_many(
        {"driver_id": driver_id},
        {"$set": {"driver_deleted": True, "driver_deleted_name": driver.get("name")}},
    )
    driver_result = await db.drivers.delete_one({"id": driver_id})
    user_result = await db.users.delete_one({"id": driver.get("user_id")})
    return {
        "message": "Livrator șters din baza de date",
        "deleted_driver": driver_result.deleted_count,
        "deleted_user": user_result.deleted_count,
        "deleted_schedules": schedules_result.deleted_count,
        "released_emergency_slots": len(touched_emergency_slots),
    }


@router.post("/{driver_id}/verify-email")
async def verify_driver_email(driver_id: str, data: DriverEmailVerification, current_user: dict = Depends(get_current_user)):
    driver = await db.drivers.find_one({"id": driver_id}, {"_id": 0})
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    if current_user["role"] == "driver" and current_user.get("driver_id") != driver_id:
        raise HTTPException(status_code=403, detail="Nu poți verifica alt livrator")
    if current_user["role"] not in ["admin", "driver"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    expires_raw = driver.get("email_verification_expires_at")
    code_hash = driver.get("email_verification_code_hash")
    if not code_hash or not expires_raw:
        raise HTTPException(status_code=400, detail="Nu există cod activ")
    expires_at = datetime.fromisoformat(expires_raw.replace("Z", "+00:00"))
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Cod expirat. Cere retrimiterea codului.")
    if not verify_password(data.code.strip(), code_hash):
        raise HTTPException(status_code=400, detail="Cod invalid")

    verified_at = datetime.now(timezone.utc).isoformat()
    update = {
        "email_verified": True,
        "email_verified_at": verified_at,
        "email_verification_code_hash": None,
        "email_verification_expires_at": None,
    }
    await db.drivers.update_one({"id": driver_id}, {"$set": update})
    await db.users.update_one({"id": driver["user_id"]}, {"$set": update})
    return {"message": "Email verificat", "email_verified": True}


@router.post("/{driver_id}/resend-verification")
async def resend_driver_verification(driver_id: str, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    driver = await db.drivers.find_one({"id": driver_id}, {"_id": 0})
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    if driver.get("email_verified"):
        return {"message": "Emailul este deja verificat", "email_verified": True}
    try:
        email_delivery = await _create_and_send_verification(driver_id, driver["user_id"], driver["email"], driver["name"])
    except EmailDeliveryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"message": "Cod retrimis", "email_delivery": email_delivery}


@router.put("/{driver_id}/location")
async def update_driver_location(driver_id: str, latitude: float, longitude: float, current_user: dict = Depends(get_current_user)):
    driver = await _ensure_admin_or_self(driver_id, current_user)
    if driver.get("driver_status") == "offline" and not driver.get("current_order_id"):
        return {"message": "Livrator offline; locația nu este urmărită", "ignored": True}
    await db.drivers.update_one(
        {"id": driver_id},
        {"$set": {"latitude": latitude, "longitude": longitude}}
    )
    return {"message": "Location updated"}


@router.put("/{driver_id}/status")
async def update_driver_status(
    driver_id: str,
    data: DriverStatusUpdate | None = Body(default=None),
    is_active: bool | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
):
    driver = await _ensure_admin_or_self(driver_id, current_user)
    if data is None:
        status = "active" if is_active else "offline"
        break_minutes = None
    else:
        status = data.status
        break_minutes = data.break_minutes
    if driver.get("current_order_id") and status in {"break", "offline"}:
        raise HTTPException(status_code=409, detail="Livratorul este în livrare. Finalizează sau reasignează comanda înainte de pauză/offline.")

    now = datetime.now(timezone.utc)
    update = {
        "driver_status": status,
        "is_active": status in ACTIVE_DRIVER_STATUSES,
        "status_updated_at": now.isoformat(),
    }
    if status == "break":
        minutes = max(1, min(int(break_minutes or 30), 180))
        update["break_started_at"] = now.isoformat()
        update["break_until"] = (now + timedelta(minutes=minutes)).isoformat()
    elif status == "active":
        update["current_order_id"] = driver.get("current_order_id")
        update["last_online_at"] = now.isoformat()
    elif status != "break":
        update["break_started_at"] = None
        update["break_until"] = None
    await db.drivers.update_one(
        {"id": driver_id},
        {"$set": update}
    )
    if current_user["role"] == "admin":
        await _log_driver_audit(driver_id, current_user, "driver_status_updated", update)
    return {"message": "Status updated", "operational_status": status, "is_active": update["is_active"]}
