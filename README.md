# EazyFill

Production-focused monorepo for EazyFill:

- FastAPI backend and admin APIs in `backend/`
- React admin dashboard in `frontend/`
- Chrome MV3 extension in `extension/`
- Firefox extension variant in `extension-firefox/`
- Runtime data marker in `data/README.md`

## Repository Layout

- `backend/`: API, services, migrations, scheduler, workers, and tests.
- `frontend/`: Admin UI built with Vite and React.
- `extension/`: Chromium extension source for development and store preparation.
- `extension-firefox/`: Firefox-specific extension source.
- `docs/`: privacy, QA, readiness, launch, and audit notes.
- `scripts/`: active QA, smoke-test, backup, billing, and local helper scripts.
- `trash/`: retired legacy material kept for review; excluded from Docker builds.

## Local Development

Backend:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
PYTHONPATH=backend python -m app.main
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Extension:

Load `extension/` as an unpacked extension in Chromium browsers. Load
`extension-firefox/` for Firefox-specific testing.

## Validation

```bash
python -m compileall -q backend/app backend/migrations
python -m pytest backend/tests -q
node --check extension/options/options.js
node --check extension-firefox/options/options.js
cd frontend && npm run build
```

## Docker And Portainer

The canonical deployment path is:

- `Dockerfile`
- `docker-compose.yml`
- optional `docker-compose.prod.yml`
- `.env.example`

The published image is:

```text
ghcr.io/jack101a/eazyfill:latest
```

Runtime data, database files, Redis data, backups, config, uploaded models, and
learned mappings must live on host-mounted volumes under `CONFIG_PATH`. They
are intentionally not committed or baked into the Docker image.

See `DEPLOYMENT.md` for the Portainer checklist.
