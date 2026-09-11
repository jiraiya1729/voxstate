# Voxstate Client

Stage 1 operator console for initiating an AI phone call through the FastAPI backend.

## Local Development

Create `.env.local` from `.env.example`, then run the backend and frontend separately.

```powershell
cd E:\voxstate\server
docker compose up -d --wait postgres
uv sync --dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

```powershell
cd E:\voxstate\client
npm install
npm run dev
```

Open `http://localhost:3000`. Provider credentials remain in `server/.env`; the frontend
contains only the server-side `VOXSTATE_BACKEND_URL` used by its route handlers.
