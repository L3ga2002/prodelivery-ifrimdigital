# OpenClaw corrected retry report: ifrim-reviewer

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
No current P0/P1 confirmed in the code I reviewed. The old critical items for seed gating, public role escalation, order tenant authz, driver profile authz, and driver schedule authz are now fixed in source. Preview was down on both expected ports, so I could not complete live browser/API flow verification.

[P2] Cookie auth has no CSRF/origin protection for unsafe methods  
File/line: [backend/auth.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/auth.py:76>)  
Owner/fixer: ifrim-backend | ifrim-security  
Evidence: HTTPS cookies are issued with `SameSite=None` at lines 77-95, and `axios.defaults.withCredentials = true` is enabled in [frontend/src/context/AuthContext.js](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/context/AuthContext.js:7>). No CSRF token or unsafe-method `Origin`/`Referer` middleware was found.  
Impact: Logged-in admin/restaurant/driver sessions rely on browser cookies for state-changing routes. If production uses cross-site cookies, malicious pages can attempt credentialed mutations within the victim role’s permissions.  
Fix recipe:  
1. Prefer `SameSite=Lax` unless cross-site SPA/API cookies are truly required.  
2. If `SameSite=None` is required, add middleware that rejects unsafe methods unless `Origin` is in the trusted frontend allowlist, or implement double-submit CSRF tokens.  
3. Add regression tests for rejected cross-origin `POST/PUT/PATCH/DELETE`.  
Verification command: `curl -i -X POST http://127.0.0.1:8000/api/seed -H "Origin: https://evil.example" -b "access_token=<valid_admin_cookie>"` should return 403.

[P2] Login lockout can be bypassed with spoofed `X-Forwarded-For`  
File/line: [backend/routers/auth.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/auth.py:39>)  
Owner/fixer: ifrim-backend | ifrim-security  
Evidence: `_attempt_identifier` trusts the first `x-forwarded-for` value unconditionally, then stores lockout counters by `ip:email` at lines 45-70.  
Impact: An attacker can rotate `X-Forwarded-For` and avoid the 5-attempt / 15-minute lockout for one account.  
Fix recipe:  
1. Use `request.client.host` unless the app is behind a configured trusted proxy.  
2. Add a per-email throttle independent of IP.  
3. Add a test that varies `X-Forwarded-For` across failed attempts.  
Verification command: run 6 failed login attempts for the same email with different `X-Forwarded-For`; attempt 6 should return `429`.

[P2] CORS safety depends entirely on unverified deployment env  
File/line: [backend/server.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/server.py:42>)  
Owner/fixer: ifrim-devops | ifrim-security  
Evidence: `allow_credentials=True` uses `CORS_ORIGINS` directly at lines 42-45, then a second custom middleware echoes origins from the same env set at lines 50-66. I did not read `.env` per instructions, so production/local values remain unverified.  
Impact: A wildcard or overly broad origin list with credentialed cookies would expose authenticated API reads cross-origin. Duplicate CORS handling also increases config drift risk.  
Fix recipe:  
1. Verify deploy `CORS_ORIGINS` contains only explicit trusted frontend origins, never `*`.  
2. Fail startup if `allow_credentials=True` and any origin is `*`.  
3. Remove the custom CORS echo middleware unless there is a documented reason.  
Verification command: `curl -i -H "Origin: https://evil.example" http://127.0.0.1:8000/api/` must not include `access-control-allow-origin: https://evil.example`.

[P2] Order numbers race under concurrent order creation  
File/line: [backend/routers/orders.py](<C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/orders.py:207>)  
Owner/fixer: ifrim-backend  
Evidence: normal orders and problem orders use `count_documents({}) + 1` for `order_number` at lines 207-208 and 339-344. No unique index or atomic counter was found.  
Impact: Two simultaneous orders can receive the same visible order number, which breaks dispatch, restaurant support, customer references, and reconciliation.  
Fix recipe:  
1. Add an atomic counters collection using `find_one_and_update(..., $inc, upsert=True, ReturnDocument.AFTER)`.  
2. Add a unique index on `orders.order_number`.  
3. Cover normal and problem-order creation with a concurrency test.  
Verification command: run a parallel order-create test with 20 requests and assert all returned `order_number` values are unique.

[P3] Preview unavailable for end-to-end verification  
File/line: `.ifrim/PREVIEW.md` expected `http://127.0.0.1:3000` and `http://127.0.0.1:8000/api/`  
Owner/fixer: ifrim-devops | ifrim-qa  
Evidence: `Invoke-WebRequest` to both expected ports returned “actively refused”.  
Impact: Current UI/API readiness could not be verified live in this retry.  
Fix recipe: start `.\dev-start.ps1`, confirm health, then run smoke flows for admin, restaurant, and driver.  
Verification command: `Invoke-WebRequest http://127.0.0.1:8000/api/` and `Invoke-WebRequest http://127.0.0.1:3000` should return 200-class responses.

Residual notes: prior P0/P1 issues in `.ifrim/OPEN_ISSUES.md` appear stale based on current source and should be moved to resolved after QA re-runs `backend/tests/test_security_authorization.py`. I did not edit files and did not open forbidden env/private/upload paths.

