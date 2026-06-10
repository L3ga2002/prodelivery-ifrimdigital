# claude-fable-principal

- Date: 2026-06-09 23:29:15
- Profile: fable
- Agent: ifrim-claude-fable-principal
- Model: fable
- Effort: high
- Task: Run an end-to-end security audit of the ProDelivery project. Use Fable-level reasoning. Read project memory first, then inspect backend, frontend, auth, role authorization, tenant isolation, MongoDB query scoping, seed/admin/debug endpoints, secrets exposure, uploaded files, CORS, dependency/build risks, and developer scripts. Do not edit files. Do not read .env, .env.*, *.env, memory/test_credentials.md, .ifrim/private/**, .ifrim/tmp/**, or backend/uploads/**. Return confirmed findings ordered by severity with file/line, evidence, exploit scenario, impact, concrete fix recipe, verification command, and recommended owner. Also include a short attack-surface map and a prioritized remediation plan.

---
# Security Audit - IfrimDigital ProDelivery (Fable-level)

I read `CLAUDE.md`, `.ifrim/NEXT_SESSION.md`, `PROJECT_STATE.md`, `OPEN_ISSUES.md`, and `AGENTS.md` first. `OPEN_ISSUES.md` already lists the auth/seed/authorization concerns as open P0/P1 items - this audit confirms they are still present in code and adds precise file/line evidence, exploit paths, and fixes. I did not edit files and did not read any excluded secret/upload paths.

---

## 1. Executive Verdict

**Not production-safe. Multiple confirmed P0 vulnerabilities.** The backend authenticates requests but performs almost **no role or tenant authorization** on its core business endpoints. Three independent critical issues each allow full compromise:

1. An **unauthenticated** `POST /api/seed` endpoint wipes the database and returns admin credentials.
2. **Self-service privilege escalation**: `POST /api/auth/register` accepts an arbitrary `role`, so anyone can register as `admin`.
3. **Broken object/tenant authorization (IDOR)** across orders/drivers: any logged-in user can read and mutate every tenant's orders and customer PII.

These are confirmed by direct code reading, not hypotheses. Remediation is concentrated (auth dependencies + a role/tenant guard layer), so a focused fix can close the bulk of risk quickly.

Confirmed positives: passwords are bcrypt-hashed; JWTs use HS256 with typed access/refresh separation and short access TTL; tokens are httpOnly cookies (not `localStorage`); avatar uploads are re-encoded via Pillow with size/type limits and UUID filenames (no path traversal); `.gitignore` covers `.env*`, `backend/uploads/`, and `memory/test_credentials.md`.

---

## 2. Attack-Surface Map

| Surface | Auth required? | Authz enforced? | Notes |
|---|---|---|---|
| `POST /api/seed` | **No** | **No** | Destroys + reseeds DB; leaks demo admin creds |
| `POST /api/auth/register` | No (public) | **Role unvalidated** | Privilege escalation to admin |
| `POST/GET /api/auth/login,me,refresh,logout` | mixed | n/a | Lockout keyed on spoofable `X-Forwarded-For` |
| `/api/orders/**` | Yes | **Mostly none** | IDOR read + mutate across all restaurants/drivers |
| `/api/drivers` & `/api/drivers/{id}` (GET) | Yes | **None** | PII (CNP, birth date, phone, earnings) to any user |
| `/api/drivers/**` (mutations) | Yes | Admin/self guarded (good) | `_ensure_admin_or_self` used correctly |
| `/api/restaurants/**` | Yes | Partial (good on most) | `get_restaurants` lists all to any user |
| `/api/schedules/driver/{id}` (GET) | Yes | **None** | Read any driver schedule |
| `/api/schedules/admin/**`, `/zones` mutations, emergency admin | Yes | Admin-guarded (good) | Consistent `role == "admin"` checks |
| `/api/drivers/{id}/avatars/{id}/image` | **No** | No | Public image serving |
| `/api/geocoding/search` | Yes | n/a | Server-side rate-limited proxy (good) |
| CORS middleware | n/a | env-driven | Verify `CORS_ORIGINS` != `*` with credentials |

---

## 3. Findings by Severity

### P0-1 - Unauthenticated database wipe + credential disclosure via `/api/seed`
- **File/line:** `backend/routers/seed.py:513-514` (`@router.post("/seed")` has **no** `Depends(get_current_user)`), destructive helper `clear_demo_collections` at `:188-195`, credential return at `:553-559`. Registered under `/api` in `backend/server.py:27`.
- **Evidence:** `async def seed_data():` takes no auth dependency. It calls `clear_demo_collections()` which runs `db.users.delete_many({"role": {"$ne": "admin"}})`, `db.drivers.delete_many({})`, `db.restaurants.delete_many({})`, `db.orders.delete_many({})`, `db.emergency_slots...`, `db.schedules...`, `db.delivery_zones...`, then returns demo admin email + password in the JSON body.
- **Exploit scenario:** `curl -X POST https://host/api/seed` - no token - deletes all production orders, restaurants, drivers, schedules, zones, and non-admin users, then resets admin to the demo password and prints it. Full data destruction + admin takeover.
- **Impact:** Catastrophic: data loss, denial of service, account takeover.
- **Fix recipe:** Add `current_user: dict = Depends(get_current_user)` and require `current_user["role"] == "admin"`; additionally gate behind an env flag (e.g. `ALLOW_SEED=true`) so it cannot run in production at all. Remove credentials from the response body.
- **Verification:** `curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:8000/api/seed` must return `401`/`403` (not `200`); with admin token + `ALLOW_SEED` unset it should still be blocked.
- **Owner:** backend / security.

### P0-2 - Privilege escalation: arbitrary `role` accepted at registration
- **File/line:** `backend/models/user.py:16-20` (`role: str` - unconstrained) consumed at `backend/routers/auth.py:84-90` (`role=user_data.role`). Also `restaurant_id=user_data.restaurant_id` is attacker-controlled (`auth.py:89`).
- **Evidence:** `UserCreate` declares `role: str` with no `Literal`/enum and no server-side override; `register()` passes it straight into the persisted `User`. The issued token then carries `role: "admin"`.
- **Exploit scenario:** `POST /api/auth/register {"email":"x@x.io","password":"...","name":"x","role":"admin"}` -> returns an admin session cookie/token. Alternatively `role":"restaurant","restaurant_id":"rest-001"` impersonates an existing restaurant tenant.
- **Impact:** Complete authorization bypass; any anonymous user becomes admin or any restaurant.
- **Fix recipe:** Force public self-registration to a non-privileged role only (e.g. ignore client `role` and set `"customer"`/`"driver"` per a controlled flow). Constrain the model: `role: Literal["driver","restaurant","admin"]` and never accept `admin` from a public endpoint. Ignore client-supplied `restaurant_id` unless verified. Admin/restaurant/driver creation already has dedicated admin-gated endpoints (`drivers.py:405`, `restaurants.py:157`) - route privileged creation only through those.
- **Verification:** `POST /api/auth/register` with `role:"admin"`, then `GET /api/auth/me` - role must not be `admin`.
- **Owner:** backend / security.

### P0-3 - Broken object/tenant authorization on orders (IDOR, read + write)
- **File/line:** `backend/routers/orders.py` - `get_orders:95-103`, `get_driver_orders:106-112`, `get_restaurant_orders:115-121`, `get_order:124-129`, `create_order:132`, `assign_order:185`, `set_preparing:215`, `set_ready:297`, `update_order_status:326`. None check `role` or tenant ownership.
- **Evidence:** `get_orders` returns `db.orders.find({}, ...).to_list(1000)` to **any** authenticated user. `get_restaurant_orders` queries by the path `restaurant_id` with no comparison to `current_user["restaurant_id"]`. `update_order_status`/`assign_order` mutate any order by id with no ownership/role check.
- **Exploit scenario:** A driver or any restaurant account logs in and calls `GET /api/orders` -> harvests **all** customers' names, phones, addresses, and order values platform-wide (GDPR breach). A malicious restaurant calls `GET /api/orders/restaurant/{competitor_id}` to read a competitor's volume, or `PUT /api/orders/{id}/status {"status":"CANCELLED","cancellation_reason":"x"}` to sabotage another restaurant's orders, or `PUT /api/orders/{id}/assign` to reassign drivers.
- **Impact:** Mass PII disclosure + cross-tenant data tampering/sabotage.
- **Fix recipe:** Introduce a reusable authorization layer. For reads: admin -> all; restaurant -> inject `{"restaurant_id": current_user["restaurant_id"]}` into every query; driver -> `{"driver_id": current_user["driver_id"]}`. For `get_order`/status/assign: load the order, then assert the caller is admin, the owning restaurant, or the assigned driver (with allowed status transitions per role). Restrict `assign_order`/`create_order` to admin/restaurant as appropriate.
- **Verification:** As a seeded restaurant token, `GET /api/orders` must return only that restaurant's orders; `PUT /api/orders/{other_restaurant_order}/status` must return `403`.
- **Owner:** backend / security.

### P1-1 - Driver PII exposure to any authenticated user
- **File/line:** `backend/routers/drivers.py:307-312` (`get_driver` returns full driver doc) and `:270-278` (`get_drivers` lists all). Driver doc fields include `cnp`, `birth_date`, `gender`, `phone`, `total_earnings` (`backend/models/driver.py:17-35`).
- **Evidence:** `get_driver` returns `db.drivers.find_one({"id": driver_id})` with no role/self guard, unlike the correctly guarded `get_driver_dashboard` (`:315`) and mutations that use `_ensure_admin_or_self`.
- **Exploit scenario:** Any logged-in user (e.g. a restaurant or any driver) enumerates `GET /api/drivers/{id}` to read other drivers' CNP (national ID) and birth dates.
- **Impact:** Sensitive personal-identifier disclosure (GDPR-significant: CNP).
- **Fix recipe:** Gate `get_driver` with `_ensure_admin_or_self`; for the `get_drivers` list, restrict to admin or project out PII (`cnp`, `birth_date`, `total_earnings`) for non-admin callers.
- **Verification:** `GET /api/drivers/{id}` as a non-owning driver/restaurant token -> `403` or response without `cnp`/`birth_date`.
- **Owner:** backend / security.

### P1-2 - Unauthorized read of any driver's schedule
- **File/line:** `backend/routers/schedules.py:288-294` (`get_driver_schedules`) - no ownership/role check (contrast with `update_schedule:318` which does check).
- **Evidence:** Returns `db.schedules.find({"driver_id": driver_id, ...})` for any path-supplied driver id.
- **Exploit scenario:** Any authenticated user maps every driver's working hours/availability.
- **Impact:** Operational/PII leakage (lower sensitivity than P1-1).
- **Fix recipe:** Apply the same admin-or-self check used in `ensure_schedule_access`/`update_schedule`.
- **Verification:** `GET /api/schedules/driver/{other_id}` as a driver -> `403`.
- **Owner:** backend.

### P2-1 - No CSRF protection on cookie-authenticated state changes
- **File/line:** `backend/auth.py:76-97` (`set_auth_cookies`; `samesite="none"` when HTTPS) and `get_current_user:144-155` (accepts the cookie for all mutating routes).
- **Evidence:** Auth is accepted via httpOnly cookie; in production (HTTPS) cookies are issued `SameSite=None`, so browsers send them on cross-site requests. No CSRF token / origin check exists for POST/PUT/PATCH/DELETE.
- **Exploit scenario:** A logged-in admin visits a malicious page that auto-submits `POST /api/seed` or `PUT /api/orders/{id}/status`; the browser attaches the cookie. (Severity is bounded by also fixing the authz issues above.)
- **Impact:** Cross-site state changes against authenticated users.
- **Fix recipe:** Prefer `SameSite=Lax` (or `Strict`) for the cookie even on HTTPS unless a true cross-site front end is required; if cross-site is required, add a double-submit CSRF token or enforce an `Origin`/`Referer` allowlist on unsafe methods.
- **Verification:** Cross-origin `fetch` with `credentials:'include'` to a mutating endpoint is rejected; same-origin app still works.
- **Owner:** security / backend.

### P2-2 - Login lockout bypass via spoofable `X-Forwarded-For`
- **File/line:** `backend/routers/auth.py:38-41` (`_attempt_identifier` trusts `x-forwarded-for` first token).
- **Evidence:** The brute-force counter keys on `f"{ip}:{email}"` where `ip` derives from an attacker-controlled header when present.
- **Exploit scenario:** Attacker rotates `X-Forwarded-For` per request to keep `failed_count` low, defeating the 5-attempt/15-min lockout and enabling password brute force.
- **Impact:** Account-takeover risk via brute force; lockout becomes ineffective.
- **Fix recipe:** Only trust `X-Forwarded-For` when behind a known proxy (configure trusted-proxy count) and otherwise use `request.client.host`; additionally rate-limit per-email globally, not only per-IP.
- **Verification:** Repeated failed logins with varying `X-Forwarded-For` still trigger `429` after the threshold.
- **Owner:** backend / security.

### P2-3 - `dev-stop.ps1` kills any process bound to ports 3000/8000
- **File/line:** `dev-stop.ps1:5-19` (`Stop-Process -Id $processId -Force` for whatever owns the port). Already noted in `OPEN_ISSUES.md`.
- **Evidence:** It force-kills the owning PID of ports 3000/8000 without verifying it is the project's uvicorn/yarn process.
- **Impact:** Local developer disruption (could terminate unrelated dev servers). Not a remote risk.
- **Fix recipe:** Track and store the PIDs started by `dev-start.ps1` (e.g. in `.codex-run/`) and stop only those; or verify the process image path before killing.
- **Verification:** Run with an unrelated process on :3000 and confirm it is not killed.
- **Owner:** devops.

### P3-1 - Public driver avatar image endpoint
- **File/line:** `backend/routers/drivers.py:561-570` - `get_driver_avatar_image` has no `Depends(get_current_user)`.
- **Evidence:** Returns image bytes for any `driver_id`/`avatar_id` pair with no auth. Ids are UUIDs (not trivially enumerable), and file path comes from DB (no traversal).
- **Impact:** Low - driver photos served without auth.
- **Fix recipe:** If avatars are non-public, require auth (admin/self) or signed URLs; otherwise accept as intended and document it.
- **Owner:** backend (low priority).

### P3-2 - `get_restaurants` and `/stats` expose all-tenant data to any role
- **File/line:** `backend/routers/restaurants.py:24-27`; `backend/routers/stats.py:10-46`.
- **Evidence:** Both return platform-wide data to any authenticated user. Restaurant directory may be intended-public to drivers; global stats counts are low sensitivity.
- **Impact:** Low; business-metric/info leakage.
- **Fix recipe:** Confirm intended audience; scope `/stats` to admin if it should not be visible to drivers/restaurants.
- **Owner:** backend / product decision.

---

## 4. False Positives / Uncertain Areas

- **CORS (`server.py:42-50`)** - configuration reads `CORS_ORIGINS` from env and the custom middleware echoes only allowed origins, which is correct **provided** `CORS_ORIGINS` is not `*`. I am barred from reading `.env`, so I could not confirm the value. **Action: verify `CORS_ORIGINS` contains explicit origins only** (with `allow_credentials=True`, `*` would be invalid/unsafe). Treat as a deployment check, not a confirmed defect.
- **Avatar uploads** - reviewed `utils/avatar_storage.py`: type allowlist, 10 MB cap, Pillow re-encode to WEBP, UUID filename in a fixed dir. No traversal/RCE path found. Not a finding.
- **Driver/restaurant/zone/schedule admin mutations** - these consistently enforce `role == "admin"` or `_ensure_admin_or_self`. Authorization there is sound; the gap is specifically the orders/driver-read/schedule-read endpoints above.
- **Git-tracked secrets** - `.gitignore` correctly excludes `.env*`, `backend/uploads/`, `memory/test_credentials.md`, `.ifrim/private`, `.ifrim/tmp`. I attempted `git ls-files` to confirm nothing secret is already committed but the command required approval and did not run. **Recommend Codex run:** `git -C <repo> ls-files | findstr /I ".env uploads/ test_credentials"` and confirm empty output.
- **Order number generation** (`orders.py:138-139`, `:259`) uses `count_documents` + 1 - a concurrency/uniqueness reliability bug, not security. Out of scope but worth a backlog note.

---

## 5. Prioritized Remediation Plan (implementation slices)

**Slice 1 - Lock the two anonymous escalation paths (highest ROI, smallest change):**
1. `seed.py`: add `Depends(get_current_user)` + admin check + `ALLOW_SEED` env gate; drop credentials from response. (P0-1)
2. `models/user.py` + `routers/auth.py`: constrain/override `role` (and ignore client `restaurant_id`) so public registration cannot create privileged accounts. (P0-2)

**Slice 2 - Central authorization for orders:**
3. Add a small dependency/helper (e.g. `require_roles(...)` and `scope_order_query(current_user)`); apply to every `/orders` read to inject tenant filters and to every mutation to verify ownership + allowed role/status transition. (P0-3)

**Slice 3 - Close remaining IDOR reads:**
4. Guard `drivers.get_driver` with `_ensure_admin_or_self` and project PII out of `get_drivers` for non-admins. (P1-1)
5. Guard `schedules.get_driver_schedules` with admin-or-self. (P1-2)

**Slice 4 - Hardening:**
6. CSRF: switch cookie to `SameSite=Lax` or add CSRF/origin checks on unsafe methods. (P2-1)
7. Fix lockout identifier to not trust raw `X-Forwarded-For`; add per-email throttle. (P2-2)
8. Verify `CORS_ORIGINS` and git-tracked-secret checks (deployment gate).

**Slice 5 - DevOps/cleanup:**
9. `dev-stop.ps1` targeted PID kill. (P2-3)
10. Decide auth posture for avatar image + `/stats`. (P3)

**Regression gate after each slice:**
```powershell
.\.venv\Scripts\python.exe -m compileall -q backend
.\.venv\Scripts\python.exe backend_test.py
cd frontend; yarn build
```

**Suggested next owner:** **security + backend** for Slices 1-4 (Codex to coordinate and re-run `ifrim-qa`); **devops** for Slice 5. Recommend blocking any deploy until Slices 1-3 land and are verified.
