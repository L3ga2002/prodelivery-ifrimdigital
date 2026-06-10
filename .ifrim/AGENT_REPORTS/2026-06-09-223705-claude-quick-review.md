# claude-quick-review

- Date: 2026-06-09 22:37:05
- Profile: quick
- Agent: ifrim-claude-code-reviewer
- Model: sonnet
- Effort: medium
- Task: Run a short high-signal read-only review of the current ProDelivery codebase. Limit output to the top 5 confirmed actionable issues. Focus on issues that Codex should route to backend, frontend, security, QA, or devops fixers. Do not edit files.

---

## ProDelivery Code Review - 2026-06-09

### Executive Verdict

**5 of the 5 P0/P1 security issues from the 2026-06-08 report are still present and unmitigated.** None of the backend security fixes have been applied. The codebase is not safe to expose on a public or shared network until at minimum findings #1 and #2 are resolved.

---

### Findings (Severity Order)

---

#### [P0] Finding #1 - P0: Unauthenticated seed/reset endpoint wipes all data and returns plaintext credentials

**Severity:** P0
**File/Line:** `backend/routers/seed.py:513-561` and `backend/server.py:27`

**Evidence:**
```python
# seed.py line 513 - no Depends(get_current_user), no auth guard at all
@router.post("/seed")
async def seed_data():
    ...
    await clear_demo_collections()  # wipes users, orders, drivers, restaurants
    ...
    return {
        "credentials": {
            "admin": demo_credentials["admin"],  # plaintext email + password in response
            ...
        }
    }
```
`server.py:27` registers this router unconditionally on every startup. Any unauthenticated HTTP client can POST `/api/seed` and wipe the entire database, then receive demo account credentials in the JSON response.

**Impact:** Complete data destruction + credential disclosure. One curl call from anywhere on the network destroys all production data.

**Fix Recipe:**
1. Add `current_user: dict = Depends(get_current_user)` to `seed_data()`.
2. Add role check: `if current_user["role"] != "admin": raise HTTPException(403)`.
3. Remove `credentials` from the return value.
4. Optionally: gate the entire router on `APP_ENV != "production"` using an env flag before including it in `server.py`.

**Verification Command:**
```powershell
# Should return 401, not 200
(Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/seed" -Method POST -ErrorAction SilentlyContinue).StatusCode
```

**Next Owner:** backend

---

#### [P0] Finding #2 - P0: Public registration accepts arbitrary roles, including "admin"

**Severity:** P0
**File/Line:** `backend/models/user.py:20`, `backend/routers/auth.py:84-90`

**Evidence:**
```python
# user.py line 20 - no Literal/validator, accepts any string
class UserCreate(BaseModel):
    role: str

# auth.py line 84-90 - role is passed directly, no stripping
user = User(
    role=user_data.role,   # <- attacker sends "admin"
    ...
)
```
No server-side validation prevents a POST to `/api/auth/register` with `{"role": "admin", ...}`. The resulting account is stored with `role: "admin"` and immediately granted a valid JWT with admin role in the payload.

**Impact:** Any unauthenticated person on the network can self-elevate to full admin.

**Fix Recipe:**
```python
# In UserCreate, restrict to safe public roles:
from typing import Literal
role: Literal["customer", "driver"] = "customer"
# OR explicitly default and ignore client role:
# user = User(role="customer", ...)
```

**Verification Command:**
```powershell
.\.venv\Scripts\python.exe backend_test.py
# Then manually verify: POST /api/auth/register with role=admin should not create an admin user
```

**Next Owner:** backend

---

#### [P1] Finding #3 - P1: GET /orders returns all orders (with customer PII) to any authenticated user

**Severity:** P1
**File/Line:** `backend/routers/orders.py:95-103`

**Evidence:**
```python
@router.get("")
async def get_orders(current_user: dict = Depends(get_current_user)):
    orders = await db.orders.find({}, {"_id": 0}).to_list(1000)
    # No role filter, no tenant filter - full list returned to driver, restaurant, anyone
    return orders
```
Confirmed by `Grep` that the only two `403` checks in the entire `orders.py` file are at lines 239-240 and 255-256 (both are narrow restaurant-specific guards on two minor endpoints). The main `GET /orders`, `GET /orders/{id}`, `PUT /orders/{id}/status`, `PUT /orders/{id}/assign`, `PUT /orders/{id}/preparing`, `PUT /orders/{id}/ready` all have **no role or ownership enforcement**.

**Impact:** Any driver or restaurant account can enumerate all orders for all restaurants, including customer names, phone numbers, and addresses. Any user can cancel, reassign, or change the status of any order.

**Fix Recipe:**
- `GET /orders`: filter by role - admin gets all; restaurant gets `{"restaurant_id": user.restaurant_id}`; driver gets `{"driver_id": user.driver_id}`; customer gets their own orders.
- `PUT /{id}/status`: verify caller is the assigned driver (for ACCEPTED/PICKED_UP/DELIVERED) or admin/restaurant (for CANCELLED/PREPARING/READY).
- `PUT /{id}/assign`: admin only.

**Verification Command:**
```powershell
# Log in as a restaurant user, then call GET /api/orders
# Should return only that restaurant's orders, not all 100+
.\.venv\Scripts\python.exe backend_test.py
```

**Next Owner:** backend

---

#### [P1] Finding #4 - P1: GET /drivers/{driver_id} exposes full driver document including national ID (CNP) and birth date to any authenticated user

**Severity:** P1
**File/Line:** `backend/routers/drivers.py:307-312`, `backend/models/driver.py:19-21`

**Evidence:**
```python
# drivers.py line 307-312 - no admin-or-self check
@router.get("/{driver_id}")
async def get_driver(driver_id: str, current_user: dict = Depends(get_current_user)):
    driver = await db.drivers.find_one({"id": driver_id}, {"_id": 0})
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    return driver   # <- full document, including cnp, birth_date
```
```python
# driver model lines 19-21
birth_date: Optional[str] = None
cnp: Optional[str] = None   # Romanian National Identification Number
```
The `GET /drivers` (list, line 270) also returns the full enriched driver document to any authenticated user.

**Impact:** Any restaurant user or even another driver can fetch the Romanian CNP (national ID number) and birth date of every driver - GDPR Category 1 sensitive personal data.

**Fix Recipe:**
```python
@router.get("/{driver_id}")
async def get_driver(driver_id: str, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin" and current_user.get("user_id") != driver["user_id"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    # Return a sanitized response model that excludes cnp, birth_date for non-admin callers
```
Also add a Pydantic `DriverPublicResponse` model that omits `cnp`, `birth_date`, `id_card_*` fields for non-admin projection.

**Verification Command:**
```powershell
# Log in as a restaurant user, GET /api/drivers/driver-001
# Should return 403, not the full driver document
.\.venv\Scripts\python.exe backend_test.py
```

**Next Owner:** backend, security

---

#### [P2] Finding #5 - P2: `dev-stop.ps1` unconditionally kills any process on ports 3000/8000 - can destroy unrelated local processes

**Severity:** P2
**File/Line:** `dev-stop.ps1` (as documented in `.ifrim/OPEN_ISSUES.md` and `AGENT_REPORTS/2026-06-08-code-review.md`, not yet fixed)

**Evidence:** The open issues file explicitly records this as known and unresolved. The script uses port-based process killing which is unsafe on a developer machine where port 3000 or 8000 might be occupied by other services.

**Impact:** Developer data loss or unexpected termination of unrelated processes. On a shared dev machine this is a minor reliability hazard; on a CI/CD machine it could kill unrelated build agents.

**Fix Recipe:**
```powershell
# In dev-stop.ps1, only kill processes whose CommandLine matches the known server paths:
Get-Process | Where-Object {
    $_.MainModule.FileName -like "*uvicorn*" -or $_.CommandLine -like "*server.py*"
} | Stop-Process -Force
# Same for node/yarn dev on port 3000
```

**Verification Command:**
```powershell
# Before running dev-stop.ps1, start a separate netcat/simple server on port 3000
# Verify it is NOT killed by dev-stop.ps1 after the fix
```

**Next Owner:** devops

---

### False Positives / Uncertain Areas

- **LoginPage demo credentials**: Already confirmed resolved - credentials are gated behind `REACT_APP_ENABLE_DEMO_LOGIN === "true"` env flag and read from env vars, not hardcoded strings. [OK] Not a false positive from prior report - it's fixed.
- **CORS middleware**: `server.py:50` builds `ALLOWED_CORS_ORIGINS` from env and enforces it - this is correct and not a finding.
- **`dev-start.ps1` health check**: Not re-read this session; marked as unverified, inherit from previous report.

---

### Suggested Next Owners

| Finding | Owner |
|---|---|
| #1 Seed endpoint auth | **backend** |
| #2 Registration role escalation | **backend** |
| #3 Orders cross-tenant leak | **backend** |
| #4 Driver PII exposure | **backend + security** |
| #5 dev-stop.ps1 port kill | **devops** |
