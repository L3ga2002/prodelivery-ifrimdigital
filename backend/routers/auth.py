from fastapi import APIRouter, HTTPException, Depends, Response, Request
from datetime import datetime, timedelta, timezone
from pymongo import ReturnDocument
from database import db
from auth import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    get_current_user,
    resolve_user_context,
    set_auth_cookies,
    clear_auth_cookies,
    decode_token,
    REFRESH_TOKEN_COOKIE,
)
from models.user import User, UserCreate, UserLogin
from models.driver import Driver

router = APIRouter(prefix="/auth", tags=["auth"])
FAILED_LOGIN_LIMIT = 5
LOCKOUT_MINUTES = 15


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _attempt_identifier(request: Request, email: str) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    ip = forwarded_for.split(",")[0].strip() or (request.client.host if request.client else "unknown")
    return f"{ip}:{email}"


async def _ensure_not_locked(request: Request, email: str) -> None:
    attempt = await db.login_attempts.find_one({"identifier": _attempt_identifier(request, email)}, {"_id": 0})
    locked_until = _parse_dt((attempt or {}).get("locked_until"))
    if locked_until and locked_until > _now_utc():
        raise HTTPException(status_code=429, detail="Prea multe încercări eșuate. Încearcă din nou mai târziu.")


async def _record_failed_login(request: Request, email: str) -> None:
    now = _now_utc()
    identifier = _attempt_identifier(request, email)
    update = {
        "$set": {"email": email, "last_failed_at": now.isoformat()},
        "$inc": {"failed_count": 1},
        "$setOnInsert": {"identifier": identifier, "created_at": now.isoformat()},
    }
    attempt = await db.login_attempts.find_one_and_update(
        {"identifier": identifier},
        update,
        upsert=True,
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    if int(attempt.get("failed_count", 0)) >= FAILED_LOGIN_LIMIT:
        await db.login_attempts.update_one(
            {"identifier": identifier},
            {"$set": {"locked_until": (now + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()}},
        )


async def _clear_failed_logins(request: Request, email: str) -> None:
    await db.login_attempts.delete_one({"identifier": _attempt_identifier(request, email)})


@router.post("/register")
async def register(user_data: UserCreate, request: Request, response: Response):
    normalized_email = user_data.email.strip().lower()
    existing = await db.users.find_one({"email": normalized_email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=normalized_email,
        name=user_data.name,
        role=user_data.role,
        phone=user_data.phone,
        restaurant_id=user_data.restaurant_id
    )

    doc = user.model_dump()
    doc["password_hash"] = hash_password(user_data.password)
    doc["created_at"] = doc["created_at"].isoformat()

    await db.users.insert_one(doc)

    if user_data.role == "driver":
        driver = Driver(
            user_id=user.id,
            name=user.name,
            phone=user_data.phone or ""
        )
        await db.drivers.insert_one(driver.model_dump())

    user_payload = await resolve_user_context(user.id)
    access_token = create_access_token(user_payload)
    refresh_token = create_refresh_token(user_payload)
    set_auth_cookies(request, response, access_token, refresh_token)
    return {"token": access_token, "user": user_payload}


@router.post("/login")
async def login(credentials: UserLogin, request: Request, response: Response):
    login_identifier = credentials.email.strip().lower().replace(" ", "")
    await _ensure_not_locked(request, login_identifier)
    query = {"email": login_identifier} if "@" in login_identifier else {"phone": login_identifier}
    user = await db.users.find_one(query, {"_id": 0})
    if not user:
        await _record_failed_login(request, login_identifier)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.get("account_disabled"):
        await _record_failed_login(request, login_identifier)
        raise HTTPException(status_code=403, detail="Cont dezactivat. Contactează administratorul.")

    if not verify_password(credentials.password, user["password_hash"]):
        await _record_failed_login(request, login_identifier)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    await _clear_failed_logins(request, login_identifier)
    user_payload = await resolve_user_context(user["id"])
    access_token = create_access_token(user_payload)
    refresh_token = create_refresh_token(user_payload)
    set_auth_cookies(request, response, access_token, refresh_token)

    return {"token": access_token, "user": user_payload}


@router.post("/logout")
async def logout(response: Response):
    clear_auth_cookies(response)
    return {"message": "Logged out"}


@router.post("/refresh")
async def refresh_session(request: Request, response: Response):
    refresh_token = request.cookies.get(REFRESH_TOKEN_COOKIE)
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_token(refresh_token, "refresh")
    user_payload = await resolve_user_context(payload["user_id"])
    access_token = create_access_token(user_payload)
    set_auth_cookies(request, response, access_token, refresh_token)
    return {"token": access_token, "user": user_payload}


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return current_user
