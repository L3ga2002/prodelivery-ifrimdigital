# claude-fable-principal

- Date: 2026-06-10 20:56:30
- Profile: fable
- Agent: ifrim-claude-fable-principal
- Model: fable
- Effort: high
- Task: Deep security audit for ProDelivery using the newest high-reasoning Fable/Mythos-style model profile. Focus on auth, cookies, CSRF/origin, role escalation, tenant/object authorization, seed/dev endpoints, CORS, secrets exposure, PII, unsafe file/storage behavior, and production blockers. Do not edit files. Report findings with severity, file/line, evidence, impact, fix recipe, and verification command.

---
# Security Audit ÔÇö IfrimDigital ProDelivery (Fable principal, review-only)

I read `CLAUDE.md`, `.ifrim/NEXT_SESSION.md`, `PROJECT_STATE.md`, `OPEN_ISSUES.md`, `AGENTS.md`, and the prior audit `AGENT_REPORTS/2026-06-09-232915-claude-fable-principal.md` first, then re-read the live backend source. I did not edit files and did not open any excluded secret/upload paths.

---

## 1. Executive Verdict

**Materially improved since the 2026-06-09 audit. The three previously-confirmed P0s and both P1s are now genuinely fixed in code.** Verified remediations (confirmed facts, not hypotheses):

- `POST /api/seed` now requires `Depends(get_current_user)` + admin + `ALLOW_SEED=true` env gate, and no longer returns credentials (`seed.py:16-21, 520-564`).
- Public `POST /api/auth/register` is now hard-locked to `driver`; any other requested role returns 403, and client `restaurant_id` is ignored (`auth.py:23, 84-94`).
- Orders endpoints now enforce role + tenant scoping on every read and mutation via `_orders_query_for_user`, `_ensure_order_read_allowed`, `_ensure_status_mutation_allowed`, `_ensure_restaurant_order_mutation_allowed`; `assign_order` is admin-only (`orders.py:15-70, 155-193, 254-257`).
- `get_driver` and the driver list are admin/self-gated; PII (CNP, birth date) no longer leaks to arbitrary callers (`drivers.py:270-273, 311-313`).
- Driver schedule reads are gated by `ensure_schedule_read_access` (`schedules.py:55-62, 298-300`).

**Remaining issues are P2/P3 hardening, not open P0s.** No new critical vulnerability was found. The deploy blockers are now: (a) CSRF/SameSite posture, (b) spoofable lockout key, (c) the unverified `CORS_ORIGINS` deployment value. I recommend these be closed before production but they are not anonymous-takeover class.

Confirmed-good: bcrypt hashing; HS256 with explicit `algorithms=[...]` (no alg-confusion) and typed access/refresh separation; httpOnly cookies; Pillow re-encode + UUID filenames + size/type caps on avatars (no traversal/RCE); JWT secret and Mongo creds sourced from env, not hardcoded; demo credentials now sourced from env in seed only.

---

## 2. Attack-Surface Map (current state)

| Surface | Auth | Authz | Status |
|---|---|---|---|
| `POST /api/seed` | Yes | admin + `ALLOW_SEED` | **Fixed** |
| `POST /api/auth/register` | Public | role forcedÔćĺdriver | **Fixed** (abuse note P3-2) |
| `/api/orders/**` | Yes | role + tenant scoped | **Fixed** |
| `/api/drivers` & `/{id}` GET | Yes | admin/self | **Fixed** |
| `/api/schedules/driver/{id}` GET | Yes | admin/self | **Fixed** |
| `POST /api/auth/login` lockout | Public | n/a | **P2-2** XFF spoof |
| Cookie-auth mutations (all) | Yes | per-route | **P2-1** no CSRF, SameSite=None on HTTPS |
| CORS middleware | n/a | env-driven | **P2-3** verify `CORS_ORIGINS` |
| `GET /api/drivers/{id}/avatars/{id}/image` | **No** | none | P3-1 (likely intended) |
| `GET /api/restaurants`, `/api/stats`, `/api/stats/hourly`, `/api/zones*` | Yes | any role | P3-3 (low-sensitivity, confirm intent) |
| `GET /api/schedules/emergency` | Yes | any role | P3-4 (drivers need it; low) |
| `/api/geocoding/search` | Yes | rate-limited proxy | Good |

---

## 3. Findings by Severity

### P2-1 ÔÇö No CSRF protection on cookie-authenticated state changes (SameSite=None in production)
- **File/line:** `backend/auth.py:76-97` (`set_auth_cookies`: `same_site = "none" if secure_cookie else "lax"`), consumed by `get_current_user` for all mutating routes (`auth.py:144-155`).
- **Evidence:** Over HTTPS the auth cookie is issued `SameSite=None`, so browsers attach it on cross-site requests. No CSRF token or `Origin`/`Referer` allowlist exists for POST/PUT/PATCH/DELETE.
- **Impact:** A logged-in **admin** visiting a malicious page can be made to trigger `PUT /api/orders/{id}/assign`, `PUT /api/orders/{id}/status` (cancel), `PATCH /api/drivers/{id}/disable`, `DELETE /api/zones/{id}`, or `POST /api/seed` (if `ALLOW_SEED=true`). The authz fixes bound the blast radius to the victim's own privilege scope, but for admin that scope is the whole platform. Real cross-site state-change risk.
- **Fix recipe:** Prefer `SameSite=Lax` even on HTTPS unless a genuinely cross-site SPA is required. If cross-site is required, add a double-submit CSRF token (non-httpOnly cookie + matching header validated server-side) or enforce an `Origin` allowlist (reuse `ALLOWED_CORS_ORIGINS`) on all unsafe methods via middleware.
- **Verification:** `curl -i -X POST http://127.0.0.1:8000/api/orders -H "Origin: https://evil.example" -b "access_token=<valid>"` must be rejected; same-origin app still works. Browser: cross-origin `fetch(..., {credentials:'include'})` to a mutating route fails.
- **Owner:** security / backend.

### P2-2 ÔÇö Login lockout keyed on spoofable `X-Forwarded-For`
- **File/line:** `backend/routers/auth.py:39-42` (`_attempt_identifier` takes first token of `x-forwarded-for` unconditionally), used by `_ensure_not_locked`/`_record_failed_login` (`:45-75`).
- **Evidence:** Identifier is `f"{ip}:{email}"` where `ip` comes from the attacker-controlled header when present. Rotating `X-Forwarded-For` per request keeps `failed_count` below `FAILED_LOGIN_LIMIT=5`.
- **Impact:** The 5-attempt / 15-min lockout is trivially defeated Ôćĺ online password brute force.
- **Fix recipe:** Only trust `X-Forwarded-For` when behind a known proxy (configurable trusted-proxy hop count / `TRUSTED_PROXY=true`), otherwise use `request.client.host`. Additionally add a per-email global throttle independent of IP.
- **Verification:** Script 20 failed logins for one email varying `X-Forwarded-For` each time; the 6th+ must return `429`.
- **Owner:** backend / security.

### P2-3 ÔÇö `CORS_ORIGINS` value unverified; wildcard + credentials would be exploitable
- **File/line:** `backend/server.py:42-66` (`CORSMiddleware` with `allow_credentials=True` and `allow_origins=os.environ['CORS_ORIGINS'].split(',')`; plus a redundant custom origin-echo middleware).
- **Evidence:** Cannot read `.env` (excluded). With `allow_credentials=True`, a `CORS_ORIGINS="*"` causes Starlette to reflect the request origin with credentials ÔÇö full credentialed cross-origin access. The custom middleware also echoes any origin present in `ALLOWED_CORS_ORIGINS`, so correctness depends entirely on that env value.
- **Impact:** If misconfigured to `*` (or to overly broad origins), enables credentialed cross-origin reads of all authorized data.
- **Fix recipe:** Confirm `CORS_ORIGINS` is an explicit comma-separated allowlist (e.g. `https://app.prodelivery.ro`), never `*`. Consider removing the redundant custom middleware to avoid divergence between the two CORS code paths.
- **Verification (Codex/devops):** `python -c "import os;print(os.environ.get('CORS_ORIGINS'))"` in the deploy env ÔÇö assert no `*` and only trusted hosts. Then `curl -i -H "Origin: https://evil.example" http://127.0.0.1:8000/api/stats` must not return `access-control-allow-origin: https://evil.example`.
- **Owner:** devops / security.

### P3-1 ÔÇö Public driver avatar image endpoint
- **File/line:** `backend/routers/drivers.py:562-571` ÔÇö `get_driver_avatar_image` has no `Depends(get_current_user)`.
- **Evidence:** Serves image bytes for any `driver_id`/`avatar_id` pair without auth. IDs are UUIDs (not enumerable); path comes from DB (no traversal). Confirmed only public route besides auth + root.
- **Impact:** Low ÔÇö driver photos served without auth.
- **Fix recipe:** If avatars are non-public, require admin/self or signed URLs; otherwise document it as intended public serving.
- **Owner:** backend (low) / product decision.

### P3-2 ÔÇö Unbounded anonymous driver-account creation via registration
- **File/line:** `backend/routers/auth.py:78-113` ÔÇö public register creates a real `users` + `drivers` record with no rate limit, CAPTCHA, or admin vetting.
- **Evidence:** Each call inserts a driver document (`auth.py:102-107`); these appear in admin lists and can claim emergency slots / set schedules once active. No throttle on the register route.
- **Impact:** LowÔÇômedium: spam/junk driver accounts, DB bloat, operational noise. No privilege gain (role forced to driver).
- **Fix recipe:** Add rate limiting on `/auth/register` (per-IP, with the trusted-proxy fix from P2-2), and consider requiring email verification before a self-registered driver becomes operationally active/visible.
- **Owner:** backend.

### P3-3 ÔÇö Cross-tenant directory/metric reads available to all roles
- **File/line:** `restaurants.py:24-27` (`get_restaurants` lists all to any role); `stats.py:10-46` (`/stats`, `/stats/hourly` to any role); `zones.py:72-93,163-182` (zones list/get/detect to any authenticated user).
- **Evidence:** All return platform-wide data to any authenticated user regardless of tenant. `/stats/analytics` is correctly admin-gated (`stats.py:49-52`); the basic counters are not.
- **Impact:** Low ÔÇö business-metric and directory leakage (order/driver counts, restaurant list, zone fees/geometry).
- **Fix recipe:** Confirm intended audience. If drivers/restaurants should not see global counts, gate `/stats` and `/stats/hourly` to admin; scope restaurant/zone listings to relevant tenant where applicable.
- **Owner:** backend / product decision.

### P3-4 ÔÇö `GET /api/schedules/emergency` readable by any authenticated role
- **File/line:** `backend/routers/emergency_slots.py:242-248` ÔÇö no role check (all other emergency mutations are admin-only; claim is driver-only).
- **Evidence:** Returns all emergency slots for a week to any authenticated user.
- **Impact:** Very low ÔÇö drivers legitimately need to see claimable slots; only operational data exposed.
- **Fix recipe:** Accept as intended, or restrict to admin/driver roles for consistency.
- **Owner:** backend (optional).

---

## 4. False Positives / Uncertain Areas

- **Prior P0/P1 items in `OPEN_ISSUES.md` are stale** ÔÇö code now contradicts them. Recommend Codex move "Public seed/reset gating", "Registration arbitrary roles", "Order read/mutation authz", "Driver profile/schedule exposure" to a Resolved section citing this audit.
- **Refresh-token rotation** (`auth.py:148-158`) ÔÇö refresh reuses the same refresh token rather than rotating it. Not a vuln given 7-day TTL + httpOnly, but rotation + reuse-detection would be a hardening nicety. Not counted as a finding.
- **Order number generation** (`orders.py:207-208`, `:339`, problem-order `:344`) uses `count_documents()+1` ÔÇö a concurrency/uniqueness reliability bug (duplicate order numbers under load), **not** a security issue. Backlog note.
- **CORS double-middleware** ÔÇö redundant, not itself a vuln; flagged under P2-3 for maintainability/divergence risk only.
- **Git-tracked secrets** ÔÇö `OPEN_ISSUES.md` records the 2026-06-09 `git ls-files` check found no tracked `.env`/uploads/credentials. I did not re-run git commands (rules). Recommend Codex re-confirm before any push.

---

## 5. Prioritized Remediation Plan

**Pre-production gate (close before deploy):**
1. P2-1 CSRF/SameSite: switch cookie to `SameSite=Lax` or add CSRF-token/Origin-allowlist on unsafe methods. (auth.py + middleware)
2. P2-2 Lockout: stop trusting raw `X-Forwarded-For`; add per-email throttle. (auth.py)
3. P2-3 Verify `CORS_ORIGINS` is explicit (devops env check). Remove redundant custom CORS middleware.

**Post-gate hardening:**
4. P3-2 Rate-limit `/auth/register`.
5. P3-1 / P3-3 / P3-4 Product decisions on avatar/stat/zone/emergency read audiences.

**Housekeeping:**
6. Update `OPEN_ISSUES.md` to reflect the verified P0/P1 fixes.
7. Backlog: order-number generation race (`orders.py`).

**Regression gate after each change:**
```powershell
.\.venv\Scripts\python.exe -m compileall -q backend
.\.venv\Scripts\python.exe backend_test.py
.\.venv\Scripts\python.exe -m pytest backend\tests\test_security_authorization.py
cd frontend; yarn build
```

**Suggested next owner:** **security + backend** for items 1ÔÇô4; **devops** for the `CORS_ORIGINS` env check; **Codex** to refresh `OPEN_ISSUES.md` and re-run `ifrim-qa`. No anonymous-takeover blockers remain ÔÇö deploy can proceed once the three P2 items land and are verified.
