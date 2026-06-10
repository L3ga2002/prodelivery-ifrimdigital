# Preview

## Live Preview Rule

For ProDelivery app work, keep local preview available whenever practical.

Workflow:

1. Start or verify preview before user-facing frontend changes.
2. Use frontend `http://127.0.0.1:3000` and backend `http://127.0.0.1:8000/api/`.
3. After React/UI changes, open/check the affected route in the browser.
4. If backend behavior changes, run a targeted API smoke test or `backend_test.py`.
5. Tell Catalin the exact URL tested.
6. If preview cannot run, record the blocker here or in `OPEN_ISSUES.md`.

## URLs

- Frontend: `http://127.0.0.1:3000`
- Backend API: `http://127.0.0.1:8000/api/`
- Current browser route seen during setup: `/login`

## Commands

Start full preview:

```powershell
.\dev-start.ps1
```

Stop local preview:

```powershell
.\dev-stop.ps1
```

Backend smoke test:

```powershell
.\.venv\Scripts\python.exe backend_test.py
```

Frontend build:

```powershell
cd frontend
yarn build
```

## Notes

- `backend/.env` and `frontend/.env` are local-only.
- Do not put production secrets in project memory.
- Before production, replace demo/local credentials and re-run security review.
- Do not silently skip live preview for visible UI changes.
