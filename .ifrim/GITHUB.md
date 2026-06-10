# GitHub Plan

## Rule

ProDelivery work done with Codex/OpenClaw must use a new dedicated GitHub repository. Do not push to, overwrite, fork into, or reuse Catalin's existing repositories unless he explicitly asks.

## Proposed Repository

- Owner: `L3ga2002`
- Repository name: `prodelivery-ifrimdigital`
- Display name idea: `ProDelivery IfrimDigital`
- Visibility: private by default
- Default branch: `main`
- Local path: `C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery`

## Before First Push

1. Confirm GitHub auth can create a new repo.
2. Confirm local `git remote -v` is empty or points only to the new repo.
3. Clean or policy-approve demo credentials in:
   - `README.md`
   - `backend_test.py`
   - `frontend/src/pages/LoginPage.jsx`
   - `memory/test_credentials.md` (ignored/local)
4. Run smoke checks:
   - `.\.venv\Scripts\python.exe backend_test.py`
   - `cd frontend; yarn build`
5. Create first baseline commit.
6. Create the new private GitHub repo.
7. Add remote:
   - `origin = git@github.com:L3ga2002/prodelivery-ifrimdigital.git` or HTTPS equivalent
8. Push:
   - `git push -u origin main`

## Current GitHub Auth Status - 2026-06-08

- Codex GitHub connector profile: `L3ga2002`
- Connector installations/repositories visible: none
- Local GitHub CLI: installed, but not authenticated
- Current local remote: none

## Required User/Auth Step

To create the repo from this machine, authenticate either:

- GitHub CLI: `gh auth login`
- or install/authorize the Codex GitHub connector for the target GitHub account/repositories.
