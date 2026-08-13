# Production Delivery

This repository is a source-only production delivery for the Logo Generated web
application. It intentionally contains no customer history, generated images,
model credentials, Lark secrets, local runtime logs, SDD records, or test suites.

## Included Runtime Components

- `frontend/`: React/Vite source and reproducible npm dependency lockfile.
- `backend/src/`: FastAPI application, business services, and database migrations.
- `backend/config/app.production.toml`: non-secret production defaults.
- `backend/config/app.local.production.example.toml`: complete private production configuration template.
- `pycore/`, `pyproject.toml`, and `requirements.txt`: local Python framework,
  package metadata, and exported locked runtime dependencies.
- `deploy/`: Windows bootstrap and local production startup scripts.
- `docker-compose.yml` and `docker/`: Docker Compose production services and Nginx reverse proxy.

## Provision Before First Start

1. Install Python 3.11+ and Node.js 20+ on the deployment host.
2. Copy `backend/config/app.local.production.example.toml` to `backend/config/app.toml`, then
   edit the host-private file with the final administrator, domain, and backend
   settings. Do not commit it.
   Run `python3 deploy/generate-production-secrets.py` on the deployment host to
   generate valid Fernet keys, then run
   `python3 deploy/validate-production-config.py backend/config/app.toml`. Empty
   encryption fields are allowed for initial startup; related admin features
   remain unavailable until configured.
   Keep `enable_real_model_smoke_tests = true` when administrators need to run the
   real provider connectivity test; each test can consume provider quota.
3. Set `customer_frontend_base_url` and `admin_frontend_base_url` to the final
   HTTPS domain. Update `cors_origins` in the private `backend/config/app.toml`
   when the browser uses a different origin.
4. Create writable, persistent directories `backend/data/` and
   `backend/data/assets/`. They are runtime data and must be backed up together.
5. Run `npm ci` followed by `npm run build:real` in `frontend/`.
6. Install Python dependencies from `requirements.txt` into an isolated virtual
   environment, then start `src.production:create_app` with Uvicorn. Startup
   applies all pending SQLite migrations and initializes the first administrator.

## Docker Compose Deployment

The Compose file runs three services:

- `backend`: FastAPI on container/host port `8099`.
- `frontend`: real Vite build served by Nginx on container/host port `5175`.
- `nginx`: public HTTP entry point on port `80`, proxying API and WebSocket traffic.

Prepare the private config and persistent directories, then start the stack:

```bash
cp backend/config/app.local.production.example.toml backend/config/app.toml
mkdir -p docker-data/backend docker-data/nginx/logs
docker compose up -d --build
```

The Compose bind mount uses the whole host-private `backend/config/` directory,
and the container entry point reads `app.toml` from that directory. The file
must exist before `docker compose up`; the image's `app.production.toml` is the
copy source, not a fallback after the directory is mounted.

The backend bind mount `docker-data/backend:/app/backend/data` persists the SQLite
database and uploaded/generated assets. Never put this directory in the image or
repository. Host ports can be changed with `HTTP_PORT`, `FRONTEND_PORT`, and
`BACKEND_PORT`; keep direct frontend/backend ports restricted to the private network
when Nginx is the public entry point.

## Non-Docker Deployment Model

The Windows `deploy/*.ps1` scripts run a combined frontend/API process at
`127.0.0.1:8099`. In the Docker Compose deployment, Nginx is the public entry
point and routes the separate frontend and backend containers. For a public
Linux deployment, place the Nginx entry point behind TLS or a Cloudflare Named
Tunnel and persist `docker-data/backend/` outside ephemeral application storage.

## Data Policy

Start with an empty database. Do not copy `logo_generated.db`, any historical
asset directory, or `fresh-baseline.db` from a development machine. If a future
approved migration of live history is required, transfer the SQLite database and
its matching `backend/data/assets/` directory as one encrypted backup, while
preserving the encryption keys that protect the database-held provider and Lark
credentials.
