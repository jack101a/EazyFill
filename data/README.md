# Runtime Data

This directory is intentionally runtime-owned. Models, user mappings, learned
questions, uploaded assets, and backup payloads are imported or restored through
the admin backup/import flows instead of being committed to git.

Use the admin backup APIs or console controls to restore:

- system packages for configuration, extension settings, and model payloads
- user packages for users, keys, plans, usage, payments, sync blobs, and uploads
- Postgres packages when running the production database

Automated local and remote backup support lives in `backend/app/services/backup_service.py`
and `backend/app/background_tasks.py`.
