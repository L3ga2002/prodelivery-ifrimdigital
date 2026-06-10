# OpenClaw report: ifrim-integrations

- Generated: 2026-06-10-125357
- Project: ProDelivery
- Mode: read-only
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
**ProDelivery Integration Report**

Scope: integrations/external systems only. I stayed read-only and did not inspect `.env`, private/temp/upload/credential/token paths.

1. What this is:  
ProDelivery is a FastAPI + MongoDB + React delivery operations platform for Bacău, migrated from Emergent. Integration surface is mainly MongoDB, JWT/cookie auth, Resend email verification, Nominatim geocoding, local avatar storage, PostHog analytics, and deployment CORS/API URL wiring.

2. Already implemented:
- Backend loads env-driven MongoDB config via `MONGO_URL`/`DB_NAME` and exposes all API routers under `/api`: [database.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/database.py:9>), [server.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/server.py:22>).
- Auth uses bcrypt, JWT access/refresh cookies, Bearer fallback, refresh endpoint, lockout after failed logins: [auth.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/auth.py:11>), [routers/auth.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/auth.py:118>).
- Resend sends driver email verification codes; code hash is stored, not plaintext, except a preview fallback can return the code when Resend test-domain restrictions happen: [email_service.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/utils/email_service.py:30>), [drivers.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/drivers.py:243>).
- Address autocomplete proxies Nominatim through backend with 1-hour cache and rate limiting: [geocoding.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/geocoding.py:12>).
- Driver avatars upload through multipart, server-compress to WebP, store under backend `uploads`, and are served through API routes: [avatar_storage.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/utils/avatar_storage.py:12>), [drivers.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/drivers.py:468>).
- Frontend uses `REACT_APP_BACKEND_URL` broadly and cookie credentials through axios: [AuthContext.js](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/context/AuthContext.js:6>).
- PostHog is hardcoded in public HTML with session recording enabled: [index.html](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/public/index.html:108>).

3. Risky / incomplete / needs verification:
- CORS is fragile. Backend requires `CORS_ORIGINS`, but project notes say production had `CORS_ORIGINS="*"` and external preflight was previously intercepted at ingress. Must verify deployed OPTIONS/credentials behavior, especially with cookies: [server.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/server.py:45>).
- Resend fallback returns verification code to admin UI when test-domain restricted. Good for preview, dangerous if enabled in production path. Verify sender domain and remove/guard fallback before real client use: [drivers.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/drivers.py:260>).
- Local avatar disk storage is not production-resilient across containers/instances and stores absolute file paths in MongoDB. Needs object storage or persistent volume plan.
- Restaurant accounts are created with generated `@delivery.ro` emails and generated passwords displayed in UI, not real onboarding/email invite flow: [restaurants.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/restaurants.py:185>).
- Admin Settings are explicitly demo-only and not persisted: [SettingsTab.jsx](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/components/admin/SettingsTab.jsx:58>).
- No Stripe, Supabase, OAuth, SMS, webhook, S3/R2/Cloudinary integration found. SMS is intentionally deferred; phone verification sets `sms_not_configured`: [drivers.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/drivers.py:219>).
- PostHog project key is public by nature, but session recording on a delivery/admin app needs privacy review and env-based configuration.

4. Client-facing workflows affected:
- Login/session persistence for admin, restaurant, driver.
- Admin creates drivers, sees generated password, sends/resends Resend verification, manages driver profile/avatar.
- Driver verifies email, edits profile, uploads avatar, changes status/location.
- Admin/restaurant creates orders; restaurant manages prep/ready/problem/cancel/status.
- Restaurant creation/location selection uses Nominatim autocomplete and zones.
- Analytics/admin tracking through backend stats plus PostHog browser capture.

5. Recommended next 3 actions:
1. Production integration audit: verify deployed envs for `CORS_ORIGINS`, `JWT_SECRET`, `MONGO_URL`, `RESEND_API_KEY`, `SENDER_EMAIL`, `NOMINATIM_*`, `REACT_APP_BACKEND_URL`, and disable demo login/seed/fallback code paths outside preview.
2. Replace fragile production surfaces: move avatars to object storage or durable mounted storage, make PostHog env-configured/consent-aware, and add real restaurant onboarding instead of displayed generated credentials.
3. Run smoke checks against the real deployment: cookie login/refresh/logout, Resend delivery to non-owner inboxes, Nominatim autocomplete rate/error behavior, avatar upload/reload after restart, external CORS preflight with credentials.

6. Files Codex should understand first:
- [backend/server.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/server.py:22>)
- [backend/database.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/database.py:9>)
- [backend/auth.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/auth.py:11>)
- [backend/routers/auth.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/auth.py:118>)
- [backend/routers/drivers.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/drivers.py:243>)
- [backend/utils/email_service.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/utils/email_service.py:30>)
- [backend/routers/geocoding.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/geocoding.py:12>)
- [frontend/src/context/AuthContext.js](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/frontend/src/context/AuthContext.js:6>)
⚠️ 🛠️ `"C:\\Program Files\\PowerShell\\7\\pwsh.exe" -Command "rg -…components\\admin\\SettingsTab.jsx README.md memory\\PRD.md" (in ~\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery)` failed
