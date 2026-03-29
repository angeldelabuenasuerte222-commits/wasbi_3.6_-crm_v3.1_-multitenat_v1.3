# WHASABI

Fullstack multi-tenant project with:

- FastAPI + MongoDB backend
- React frontend
- Public chatbot per business slug
- CRM with tenant login and legacy/global mode
- Internal tenant admin panel

## Current scope

- Public business route: `/:slug`
- Public API: `/api/business/{slug}`, `/api/chat`
- CRM global/legacy: `/crm`
- CRM by tenant slug: `/crm/:slug`
- Internal tenant panel: `/internal/tenants`

Legacy fallback is still available and is controlled by `LEGACY_FALLBACK_ENABLED`.

## What belongs where

### GitHub

- Source code
- Pull requests
- CI/CD wiring if you add it later
- No runtime secrets should live here

### Backend deploy

- Runs the FastAPI app from `backend/`
- Needs MongoDB connectivity
- Needs DeepSeek API access
- Owns backend env vars such as `MONGO_URL`, `DEEPSEEK_API_KEY`, `ADMIN_PASSWORD`, `CORS_ORIGINS`

### Frontend deploy

- Serves the React SPA from `frontend/`
- Only needs to know the backend base URL through `REACT_APP_BACKEND_URL`
- Must point to the backend origin already exposing `/api`

## Required environment variables

### Backend (`backend/.env`)

Required:

```env
MONGO_URL=mongodb+srv://<user>:<password>@cluster.mongodb.net/
DB_NAME=whasabi_db
DEEPSEEK_API_KEY=sk-...
CORS_ORIGINS=http://localhost:3000,https://your-frontend.example.com
PORT=8001
ADMIN_PASSWORD=replace-with-a-strong-global-password
LEGACY_FALLBACK_ENABLED=true
```

Optional for seeding legacy configs into Mongo:

```env
SEED_PASSWORD_CAFE_MINIMA=replace-me
SEED_PASSWORD_DENTISTA_LOPEZ=replace-me
# or:
SEED_PASSWORDS_FILE=backend/scripts/seed_passwords.json
```

Reference file: `backend/.env.example`

### Frontend (`frontend/.env`)

```env
REACT_APP_BACKEND_URL=http://localhost:8001
```

Reference file: `frontend/.env.example`

## Local development

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

Windows PowerShell:

```powershell
cd backend
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py -m uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

### Frontend

```bash
cd frontend
npm ci
npm start
```

Production build:

```bash
cd frontend
npm run build
```

## Seed legacy tenants into Mongo

The seed script no longer imports the full backend runtime. It only needs Mongo access plus passwords for the slugs you want to migrate.

Example with env vars:

```bash
SEED_PASSWORD_CAFE_MINIMA=Pass123! SEED_PASSWORD_DENTISTA_LOPEZ=Pass123! python backend/scripts/seed_tenants.py
```

Example with password file:

```json
{
  "cafe-minima": "Pass123!",
  "dentista-lopez": "Pass123!"
}
```

Then:

```bash
SEED_PASSWORDS_FILE=backend/scripts/seed_passwords.json python backend/scripts/seed_tenants.py
```

## Deployment notes

### Backend

- `render.yaml` only covers the backend service
- Review and replace `CORS_ORIGINS` before deploy
- Add real secret values for `MONGO_URL`, `DEEPSEEK_API_KEY` and `ADMIN_PASSWORD` in your provider dashboard
- Keep `LEGACY_FALLBACK_ENABLED=true` until regression testing is complete

### Frontend

- Set `REACT_APP_BACKEND_URL` to your backend origin, for example `https://your-backend.example.com`
- The app will append `/api` automatically if you omit it
- Use a provider that serves the SPA fallback correctly for React Router

## Security and operational notes

- There is no default admin password
- `/crm` is the global/legacy-compatible CRM entry
- `/crm/:slug` is the tenant-scoped CRM entry
- `/internal/tenants` uses the global admin password, not tenant passwords
- `passlib==1.7.4` is pinned with `bcrypt==4.0.1` for compatibility; avoid upgrading `bcrypt` to `5.x` without revisiting auth hashing

## Quick manual smoke test

1. Open `/:slug` and confirm the public business loads
2. Send a chat message and confirm the reply works
3. Open `/crm`, log in, and verify lead listing
4. Open `/internal/tenants`, log in with the global password, and verify tenant listing
5. Toggle `LEGACY_FALLBACK_ENABLED=false` only after validating Mongo tenants still work and legacy routes fail as expected
