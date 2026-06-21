# Production Readiness Notes

These notes document the review-first items that should not be changed blindly,
because they can affect working customer flows.

## Runtime/Data Assets

Runtime data is not a git source of truth. The repository tracks only
`data/README.md`; models, mappings, hash datasets, learned questions, uploads,
and generated backup payloads are restored/imported at runtime.

Production runtime source of truth should remain the mounted host data folder:

```text
${CONFIG_PATH}/sa_helper/data -> /app/data
```

Safe current state:

- The canonical root `Dockerfile` does not copy repository `data/` into the
  production image.
- Runtime-generated folders such as extension packages, screenshots, offline
  exam data, extension error reports, and security artifacts are ignored.
- Local and cloud backup/restore is implemented in `backend/app/services/backup_service.py`.
- Automated backup scheduling is implemented in `backend/app/background_tasks.py`.

Review before changing:

- Verify a clean host can restore system, user, and PostgreSQL backup packages.
- Confirm local retention and rclone remote backup settings before deleting operator-local copies.
- Keep production model/bootstrap payloads in mounted storage or backup packages,
  not in the repository.

## Extension Permissions

The browser extension still uses broad host permissions because captcha,
autofill, user scripts, recorder tools, and diagnostics can operate across
different domains and frames.

Safe current state:

- Legacy Sarathi/stall/VCam/root extension source has been removed from the
  active repository and is excluded from clean EazyFill packages.
- Active feature execution is controlled by modular background/content code,
  backend routes, local extension toggles, and explicit userscript settings.

Review before changing:

- Audit every permission against actual usage in `extension/background/*`,
  `extension/content/*`, `extension/userscripts/*`, and `extension/lib/*`.
- Narrow `host_permissions` only after testing captcha, autofill recorder,
  autofill playback, user scripts, Firefox, and Chrome.
- Prefer incremental permission removal with version bumps and rollback-ready
  extension packages.

## Deployment Source Of Truth

The root Docker files are canonical:

- `Dockerfile`
- `docker-compose.yml`
- `docker-compose.prod.yml`

The old `infra/` deployment path has been removed to avoid duplicate and
conflicting production instructions.
