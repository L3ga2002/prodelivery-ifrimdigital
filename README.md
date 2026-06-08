# ProDelivery

Platforma IfrimDigital pentru management livrari in Bacau.

## Local Preview

Backend:

- URL: `http://127.0.0.1:8000/api/`
- Stack: FastAPI + MongoDB
- Env: `backend/.env`

Frontend:

- URL: `http://127.0.0.1:3000`
- Stack: React + CRACO + Tailwind
- Env: `frontend/.env`

Pornire completa:

```powershell
.\dev-start.ps1
```

Oprire preview:

```powershell
.\dev-stop.ps1
```

Conturile demo locale sunt configurate in fisierele `.env` locale ignorate de git.
Nu salva parole reale sau credentiale de productie in repository.

## Useful Commands

```powershell
.\.venv\Scripts\python.exe backend_test.py
```

```powershell
cd frontend
yarn build
```
