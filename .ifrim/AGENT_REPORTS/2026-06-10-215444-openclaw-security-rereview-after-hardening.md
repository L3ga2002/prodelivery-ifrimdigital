# OpenClaw security re-review after hardening

- Generated: 2026-06-10-215444
- Project: ProDelivery
- Mode: read-only

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
No blocker found in the scoped review.

The hardening looks directionally correct:

- `SameSite=None` was replaced with `SameSite=lax` for both auth cookies in [backend/auth.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/auth.py:76>). This directly reduces CSRF exposure for cookie-authenticated unsafe requests.
- CORS origins are now trimmed/parsed once, credentials remain enabled only for explicit configured origins, and unsafe requests with an untrusted `Origin` are rejected in [backend/server.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/server.py:19>) and [backend/server.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/server.py:75>).
- Login lockout no longer trusts `X-Forwarded-For`; it uses `request.client.host` plus an email-level bucket in [backend/routers/auth.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/routers/auth.py:39>).
- Regression coverage was added for HTTPS `SameSite=Lax`, unsafe cross-origin rejection, and ignoring spoofed forwarded IPs in [backend/tests/test_security_authorization.py](</C:/Users/mihai/OneDrive/Desktop/Ifrim Digital Proiecte/ProDelivery/backend/tests/test_security_authorization.py:105>).

One deployment caveat, not a blocker: `SameSite=Lax` assumes the frontend and backend are same-site in production, for example `prodeliverybacau.com` and `api.prodeliverybacau.com`. If the frontend is hosted on a different registrable domain, cookie refresh/login persistence may break and should be verified.

Recommended verification command:

```powershell
pytest backend/tests/test_security_authorization.py -k "cookies or unsafe_cross_origin or lockout or register"
```

I did not run tests because the project test/app startup path may load local env files, and you explicitly asked not to read `.env` files.

