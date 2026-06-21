# EazyFill Portainer Deployment

This repository has one canonical production Docker path:

- `Dockerfile`
- `docker-compose.yml`
- optional production overrides in `docker-compose.prod.yml`
- optional Node A remote-worker sidecar in `docker-compose.node-a-worker-access.yml`
- optional Node B worker-only stack in `docker-compose.node-b-workers.yml`
- `.env.example`

The GitHub Actions Docker workflow publishes:

```text
ghcr.io/jack101a/eazyfill
```

## Host Layout

Use one durable host folder for the stack:

```env
CONFIG_PATH=/srv/ajaxhs/config/eazyfill
```

The compose stack mounts:

```text
${CONFIG_PATH}/postgres16 -> PostgreSQL data
${CONFIG_PATH}/redis      -> Redis data
${CONFIG_PATH}/logs       -> backend logs
${CONFIG_PATH}/backups    -> local backup files
${CONFIG_PATH}/data       -> runtime models and dynamic data
${CONFIG_PATH}/config     -> backend config.yaml
```

Do not store ONNX models, user backups, database files, uploaded data, or
generated runtime artifacts in git.

## Required Environment

Copy `.env.example` into Portainer stack environment variables and replace all
`change_me_*` values.

Required secrets:

- `POSTGRES_PASSWORD`
- `REDIS_PASSWORD`
- `AUTH_HASH_SALT`
- `ADMIN_TOKEN`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `BREVO_API_KEY` when `OTP_EMAIL_ENABLED=true`
- Razorpay keys before testing payments

Required public URL:

- `PUBLIC_BASE_URL`

## Services

- `postgres`: PostgreSQL 16 primary database.
- `redis`: Redis queue/cache for CAPTCHA workers.
- `api`: FastAPI backend and React admin dashboard.
- `captcha-worker`: Redis-backed CAPTCHA solver worker.
- `scheduler`: subscription expiry and backup scheduler.

The API container runs Alembic migrations by default on startup. Worker and
scheduler containers set `RUN_MIGRATIONS=false`.

## Node B Distributed CAPTCHA Workers

EazyFill can distribute CAPTCHA solving to a second machine. Node A stays the
source of truth for Postgres, Redis, API, billing, users, and scheduler. Node B
runs only `python -m app.worker` containers and pulls jobs from Node A Redis.

The detailed runbook is in `docs/node-b-workers.md`.

Use a private network between Node A and Node B, such as WireGuard or Tailscale.
Do not expose Redis or Postgres on a public interface.

On Node A, deploy the worker-access sidecar as a small separate stack:

```bash
EAZYFILL_NODE_A_DOCKER_NETWORK=eazyfill-network
NODE_A_POSTGRES_INTERNAL_HOST=postgres
NODE_A_REDIS_INTERNAL_HOST=redis
POSTGRES_WORKER_BIND=10.99.0.1
REDIS_WORKER_BIND=10.99.0.1
POSTGRES_WORKER_PORT=15432
REDIS_WORKER_PORT=16379

docker compose --env-file .env.node-a-worker-access \
  -f docker-compose.node-a-worker-access.yml up -d
```

If your private Node A IP is not `10.99.0.1`, use the WireGuard/Tailscale/private
IP that Node B can reach.

For the current live Portainer stack named `test-stack-eazyfill`, use the
defaults in `.env.node-a-worker-access.example`:

```text
EAZYFILL_NODE_A_DOCKER_NETWORK=test-stack-eazyfill-network
NODE_A_POSTGRES_INTERNAL_HOST=test-stack-eazyfill-postgres
NODE_A_REDIS_INTERNAL_HOST=test-stack-eazyfill-redis
```

On Node B, deploy `docker-compose.node-b-workers.yml` with environment values
from `.env.node-b-workers.example`. These values must match Node A:

- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `REDIS_PASSWORD`
- `REDIS_PREFIX`
- `AUTH_HASH_SALT`
- admin credentials, if you keep them populated for operational consistency

Node B also needs the same ONNX model file at:

```text
${NODE_B_CONFIG_PATH}/data/models/model.onnx
```

Copy it from Node A or restore it from your system backup before starting Node B
workers. If Node A uses a different model filename in admin mappings, place the
same filename under Node B `data/models/` too.

Tune `SOLVER_WORKER_CONCURRENCY` for the mini PC. Start with `2`; increase only
if CPU and memory have headroom.

## Local Validation

```bash
docker compose --env-file .env.example -f docker-compose.yml -f docker-compose.prod.yml config --quiet
docker compose --env-file .env.node-a-worker-access.example -f docker-compose.node-a-worker-access.yml config --quiet
docker compose --env-file .env.node-b-workers.example -f docker-compose.node-b-workers.yml config --quiet
python -m compileall -q backend/app backend/migrations
python -m pytest backend/tests -q
cd frontend && npm run build
```

## Deploy In Portainer

1. Create or update a stack named `eazyfill`.
2. Paste `docker-compose.yml` and optionally merge `docker-compose.prod.yml`.
3. Add environment variables from `.env.example`.
4. Set `EAZYFILL_IMAGE=ghcr.io/jack101a/eazyfill:latest` or a branch/tag image.
5. Deploy the stack.
6. Confirm `/health`, `/ready`, and `/admin/`.
7. Test email OTP, signup/login, extension sync, CAPTCHA solve, backup, and Razorpay test payment.

## Smoke Test

After deployment:

```bash
EAZYFILL_BASE_URL=https://your-domain.example \
ADMIN_USERNAME=admin \
ADMIN_PASSWORD='your-admin-password' \
python scripts/smoke_check.py
```

Treat `/ready` status `error` as a deployment blocker. Status `degraded` means
the API is alive, but a noncritical fallback is active and should be reviewed.

## Production Safety Notes

- Keep `DB_TYPE=postgresql` and `LEGACY_DB_TYPE=postgresql` in production.
- Keep one API worker until OTP challenge storage is moved from process memory to a shared store.
- Keep `RUN_BACKGROUND_TASKS=false` on the API container; use the scheduler service for background jobs.
- Keep `data/`, backups, and database folders mounted on the host.
- Rotate Brevo/Razorpay/admin secrets only after staging smoke tests pass.
