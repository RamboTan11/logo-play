# Production Delivery

This repository is a source-only production delivery for the Logo Generated web
application. It intentionally contains no customer history, generated images,
model credentials, Lark secrets, local runtime logs, SDD records, or test suites.

## Included Runtime Components

- `frontend/`: React/Vite source and reproducible npm dependency lockfile.
- `backend/src/`: FastAPI application, business services, and database migrations.
- `backend/config/app.production.toml`: non-secret production defaults.
- `backend/config/app.local.production.example.toml`: private configuration template.
- `pycore/` and `pyproject.toml`: local Python framework and runtime dependencies.
- `deploy/`: Windows bootstrap and local production startup scripts.

## Provision Before First Start

1. Install Python 3.11+ and Node.js 20+ on the deployment host.
2. Copy `backend/config/app.local.production.example.toml` to
   `backend/config/app.local.toml`, then replace every `CHANGE_ME` value through
   the server secret manager or another host-private mechanism. Do not commit it.
3. Set `customer_frontend_base_url` and `admin_frontend_base_url` to the final
   HTTPS domain. Update `cors_origins` in `backend/config/app.production.toml`
   when the browser uses a different origin.
4. Create writable, persistent directories `backend/data/` and
   `backend/data/assets/`. They are runtime data and must be backed up together.
5. Run `npm ci` followed by `npm run build:real` in `frontend/`.
6. Install Python dependencies from `pyproject.toml` into an isolated virtual
   environment, then start `src.production:create_app` with Uvicorn. Startup
   applies all pending SQLite migrations and initializes the first administrator.

## Deployment Model

The backend serves both the built frontend and `/api` from one origin. The
existing `deploy/*.ps1` scripts implement this on Windows at `127.0.0.1:8099`.
For a public Linux deployment, place Uvicorn behind a TLS reverse proxy or a
Cloudflare Named Tunnel, run it under systemd or a container supervisor, and
persist `backend/data/` outside ephemeral application storage.

## Data Policy

Start with an empty database. Do not copy `logo_generated.db`, any historical
asset directory, or `fresh-baseline.db` from a development machine. If a future
approved migration of live history is required, transfer the SQLite database and
its matching `backend/data/assets/` directory as one encrypted backup, while
preserving the encryption keys that protect the database-held provider and Lark
credentials.
