# OpenClaw corrected retry report: ifrim-security-reviewer

- Generated: 2026-06-10-205602
- Project: ProDelivery
- Mode: read-only retry corrected syntax

---
|
o  Doctor warnings ------------------------------------------------------+
|                                                                        |
|  - Left plugin install index in place because shared SQLite state has  |
|    conflicting plugin install metadata for: codex                      |
|                                                                        |
+------------------------------------------------------------------------+
[state-migrations] Legacy state migration warnings:
- Left plugin install index in place because shared SQLite state has conflicting plugin install metadata for: codex
|
o  Doctor warnings ------------------------------------------------------+
|                                                                        |
|  - Left plugin install index in place because shared SQLite state has  |
|    conflicting plugin install metadata for: codex                      |
|                                                                        |
+------------------------------------------------------------------------+
[plugins] plugins.allow is empty; discovered non-bundled plugins may auto-load: codex (C:\Users\mihai\.openclaw\npm\projects\openclaw-codex-8902d781d4\node_modules\@openclaw\codex\dist\index.js). Set plugins.allow to explicit trusted ids.
**Security Report**

ProDelivery is a real multi-role delivery operations app: admin/dispatch, restaurant portal, and driver portal on FastAPI/MongoDB + React. Security-sensitive areas are auth/session cookies, role and tenant boundaries, seed/demo controls, driver PII, uploads, and operational mutations.

**Already Implemented**

Auth is JWT-based with `access_token` and `refresh_token` httpOnly cookies, 15-minute access tokens, 7-day refresh tokens, and disabled-account checks in [backend/auth.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/auth.py:76>). Public registration is limited to driver accounts in [backend/routers/auth.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/auth.py:78>). Order, driver, restaurant, schedule, and zone routes now have role/object checks; the key regression tests are in [backend/tests/test_security_authorization.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/tests/test_security_authorization.py:63>). The seed endpoint is no longer anonymous and requires both `ALLOW_SEED=true` and admin auth in [backend/routers/seed.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/seed.py:16>).

**Findings**

[P1] Cookie-authenticated mutation paths need CSRF/origin enforcement  
File/line: [backend/auth.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/auth.py:76>), [backend/server.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/server.py:41>), [backend/routers/seed.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/seed.py:520>)  
Owner: ifrim-backend  
Evidence: cookies are used for auth, HTTPS sets `SameSite=None`, CORS allows credentials, and mutating endpoints do not enforce `Origin`/CSRF tokens. `POST /api/seed` has no request body, so if `ALLOW_SEED=true` in a real environment, an admin browser could be cross-site posted into resetting demo data.  
Impact: integrity/availability risk for admin operations; worst case demo reset or other no-body cookie-authenticated state changes.  
Fix recipe:  
1. Add middleware/dependency rejecting unsafe methods unless `Origin`/`Referer` matches configured trusted frontend origins, or add CSRF token double-submit for cookie-auth flows. Keep Bearer-token API clients supported explicitly.  
2. Add negative test: cross-site `Origin: https://evil.example` with admin cookies gets 403 on `/api/seed` and representative admin mutations. Positive test: configured frontend origin succeeds.  
3. Verification: `pytest backend/tests/test_security_authorization.py -k "csrf or origin or seed"` after adding tests.

[P2] Login lockout trusts spoofable `X-Forwarded-For`  
File/line: [backend/routers/auth.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/auth.py:39>)  
Owner: ifrim-backend / ifrim-devops  
Evidence: `_attempt_identifier()` takes the first `x-forwarded-for` value before `request.client.host`. Unless the app is only reachable behind a trusted proxy that strips/sets this header, attackers can rotate the header and bypass per-IP lockout.  
Impact: account brute-force risk against admin/restaurant/driver login.  
Fix recipe:  
1. Only trust forwarded headers when a trusted proxy setting is enabled and the request source is trusted; otherwise use `request.client.host`, or move rate limiting to ingress.  
2. Add negative test: five failed attempts with different untrusted `X-Forwarded-For` values still lock the account/IP bucket. Positive test: trusted proxy mode honors the configured client IP header.  
3. Verification: `pytest backend/tests/test_iteration22_delivery_requirements.py -k bruteforce`.

[P2] Driver avatar images are publicly retrievable by UUID, including pending images  
File/line: [backend/routers/drivers.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/drivers.py:562>)  
Owner: ifrim-backend  
Evidence: `GET /api/drivers/{driver_id}/avatars/{avatar_id}/image` has no `get_current_user` dependency and only checks `is_deleted=False`. It does not require the image to be approved or the requester to be admin/self.  
Impact: driver photo/privacy leakage if an avatar URL or UUID leaks from logs, browser history, screenshots, or API responses.  
Fix recipe:  
1. Require auth; allow admin, owning driver, or public access only to `status=approved AND is_active=true` if public avatars are intended.  
2. Add negative test: anonymous request to a pending avatar returns 401/403/404; positive test: admin/self can view pending, public can view approved only if policy allows.  
3. Verification: `pytest backend/tests/test_iteration24_driver_status_avatar.py -k avatar`.

[P2] Onboarding returns initial passwords and fallback verification codes to the admin UI  
File/line: [backend/routers/drivers.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/drivers.py:460>), [backend/routers/restaurants.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/restaurants.py:201>), [frontend/src/pages/AdminDashboard.jsx](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/pages/AdminDashboard.jsx:1370>)  
Owner: ifrim-backend / ifrim-frontend  
Evidence: driver and restaurant creation return generated passwords; Resend test-domain fallback can display verification code and initial password in the UI. This may be acceptable in preview, but it is not production-safe onboarding.  
Impact: account takeover risk through admin screen exposure, browser recording, logs, support screenshots, or stale frontend state.  
Fix recipe:  
1. For production, replace returned passwords with one-time invite/reset links, or require admin-set temporary password with forced rotation and no API echo after creation. Disable verification-code fallback outside development.  
2. Add negative test: production config never returns `password` or `verification_code`; positive test: invite was created/sent and user must set password.  
3. Verification: `pytest backend/tests -k "create_driver or create_restaurant or verification"` plus inspect network response in admin create flows.

[P3] Global stats and restaurant directory are broad for every authenticated role  
File/line: [backend/routers/stats.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/stats.py:10>), [backend/routers/restaurants.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/restaurants.py:24>)  
Owner: ifrim-backend / product decision  
Evidence: `/api/stats` and `/api/restaurants` require auth but do not role-scope returned business data. `/api/stats/analytics` is admin-only, but base stats and restaurant list are global.  
Impact: business data leakage to driver/restaurant accounts if global counts, restaurant addresses, phones, or status are not intended for all roles.  
Fix recipe:  
1. Decide policy: admin global, restaurant self-scoped, driver minimal directory/status only. Apply projections and role filters.  
2. Add negative test: restaurant/driver cannot retrieve global stats or sensitive restaurant fields unless explicitly allowed. Positive test: admin still can.  
3. Verification: `pytest backend/tests/test_security_authorization.py -k "stats or restaurants"` after adding coverage.

**Workflows Affected**

Admin login/session, seed/demo reset, driver/restaurant onboarding, driver avatar upload/moderation, restaurant order operations, driver schedule/profile, and admin dashboard stats are the main client-facing workflows affected.

**Recommended Next 3 Actions**

1. Add CSRF/origin enforcement for cookie-auth unsafe methods, with `/api/seed` as the first regression case.  
2. Harden login rate limiting by removing untrusted `X-Forwarded-For` trust or moving it to trusted ingress.  
3. Decide production policy for avatar visibility and onboarding secrets, then add tests that fail if passwords/codes or pending images are exposed.

**Files Codex Should Read First**

[backend/auth.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/auth.py:76>), [backend/routers/auth.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/auth.py:39>), [backend/routers/orders.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/orders.py:15>), [backend/routers/drivers.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/drivers.py:118>), [backend/routers/seed.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/seed.py:16>), [frontend/src/context/AuthContext.js](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/context/AuthContext.js:7>), and [backend/tests/test_security_authorization.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/tests/test_security_authorization.py:63>).

I did not edit files or run tests. I also avoided the prohibited env/private/upload/credential paths.

