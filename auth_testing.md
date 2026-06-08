# Auth Testing Playbook

## MongoDB Verification
- Verifică existența utilizatorului admin în colecția `users`
- Verifică faptul că parola este hash-uită bcrypt

## API Testing
1. Login admin:
   - `POST /api/auth/login`
   - trebuie să seteze cookie-urile `access_token` și `refresh_token`
   - trebuie să returneze și `user`
2. Session check:
   - `GET /api/auth/me` cu cookie-urile din login
   - trebuie să întoarcă utilizatorul curent
3. Refresh:
   - `POST /api/auth/refresh` cu `refresh_token`
   - trebuie să seteze un nou `access_token`
4. Logout:
   - `POST /api/auth/logout`
   - trebuie să șteargă cookie-urile auth

## Frontend Testing
- Login-ul din React trebuie să funcționeze fără localStorage pentru token
- Refresh-ul paginii trebuie să păstreze sesiunea prin cookie-uri
- Logout-ul trebuie să scoată utilizatorul din sesiune

## Driver Email Verification Add-on
- Admin creează livrator prin `POST /api/drivers` cu `name`, `email`, `phone`, `vehicle_type`
- Backend setează `email_verified=false` în `users` și `drivers`
- Backend trimite cod prin Resend și salvează doar hash-ul codului
- Livratorul confirmă prin `POST /api/drivers/{driver_id}/verify-email`
- `/api/auth/me` include `email_verified` și `vehicle_type` pentru aplicația livratorului

## Driver Soft Disable Add-on
- Admin dezactivează livratorul prin `PATCH /api/drivers/{driver_id}/disable` cu `reason` opțional.
- Backend blochează dezactivarea dacă livratorul are comenzi active.
- După dezactivare, `users.account_disabled=true` și `drivers.account_disabled=true`; login-ul și `/api/auth/me` trebuie să returneze 403 pentru contul dezactivat.
