# Preview

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
