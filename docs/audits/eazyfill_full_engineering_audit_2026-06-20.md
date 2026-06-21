# EazyFill Full Engineering Audit - 2026-06-20

## 1. Project Understanding

### Product purpose
EazyFill is a browser-extension assisted productivity product for form autofill, CAPTCHA assistance, userscript management, encrypted sync/backup, and admin-operated configuration. The backend controls identity, plans, credits, billing, route/model metadata, backup packaging, and admin operations. The extension performs the user-facing browser automation with strict MV3 boundaries.

### Main user types
- End user: installs the browser extension, signs in by email OTP, uses autofill, CAPTCHA autosolve, userscripts, sync, backup, and restore.
- Admin/operator: manages plans, credits, payments, CAPTCHA model mappings, server health, backup/export, and operational settings.
- Support/operator: reviews payment or route issues, helps restore customer data, and investigates logs.

### Core workflows
- Email OTP signup/login, key/device binding, and plan entitlement loading.
- Extension popup and options workflows for profiles, autofill rules, CAPTCHA routes, userscripts, backup/restore, and account status.
- CAPTCHA route lookup/solve/proposal/learning, with credit accounting.
- Razorpay order creation, payment verification, webhook ingestion, subscription activation, and credit entitlement.
- Encrypted extension sync blob push/pull and backend backup package import/export.
- Admin dashboard management of plans, billing, models, routes, backups, and readiness.

### Architecture and technology stack
- Backend: Python FastAPI, SQLAlchemy, SQLite/PostgreSQL support, service-layer modules, middleware for auth/rate limiting/security headers, pytest tests.
- Admin frontend: React/Vite, modular dashboard panels, API client with credentials and timeout handling.
- Extension: Chrome/Firefox MV3, service worker, content scripts, userScripts API, options/popup UI, encrypted local/sync storage.
- Packaging/deployment: Docker, docker-compose, nginx config, scripts for extension packaging/audit.

### External services and dependencies
- Razorpay for payments and webhooks.
- Brevo/SMTP-style email delivery for OTP.
- Optional Redis for rate limiting/deduplication workflows.
- Optional rclone/cloud backend for backup mirroring.
- Browser extension APIs: storage, scripting, userScripts, tabs, alarms, notifications.

### Deployment model
Runtime data is intentionally outside git and expected under mounted data paths. Docker files and production readiness docs describe a backend/admin server plus packaged browser extensions. Secrets and runtime keys must come from environment variables or mounted config, not committed source.

### Critical business rules
- Credits and service entitlements must be decided by the backend, not trusted from the extension.
- Payment activation must only occur after verified Razorpay signature or explicit audited admin override.
- Extension sync blobs should remain encrypted before leaving the browser.
- Backend backup packages must protect user/system data at rest and detect tampering.
- Userscripts must execute through browser-controlled APIs, not `eval` or page-exposed secrets.

## 2. Findings by Role

### Security Engineer

#### Fixed: OTP registration lacked abuse throttling
- Area and files: `backend/app/api/v2_routes/auth.py`, `backend/tests/test_v2_eazyfill_routes.py`
- Severity: High
- Evidence: `/v2/auth/register` issued OTP challenges and email sends with only per-challenge verify attempt limits. There was no request quota before generating and sending OTP.
- Impact: A public unauthenticated endpoint could be abused for email spam, inbox flooding, cost amplification, and account annoyance.
- Reproduction scenario: Repeatedly POST the same supported email to `/v2/auth/register`; each request could create a fresh challenge and trigger delivery.
- Root cause: The OTP flow protected verification attempts but not challenge issuance.
- Fix implemented: Added a 5-minute in-memory quota by email identifier and client IP; invalid domains and missing email config are rejected before quota consumption. Duplicate outstanding challenges for the same email are dropped so the newest OTP wins.
- Risk of fix: In-memory quota is per process. Multi-instance production should move this to Redis or the existing shared rate-limit backend.
- Verification: Added tests for repeated OTP limits and latest-challenge replacement. Full backend suite passed.

#### Fixed: Backend `.upbak` packages used unauthenticated reversible obfuscation
- Area and files: `backend/app/services/backup_service.py`, `backend/tests/test_backup_service_remote_config.py`
- Severity: High
- Evidence: Backup package encryption used `_xor_stream(data, key)` for `.upbak` data.
- Impact: Anyone with package access could tamper with ciphertext undetected; XOR-style reversible streams are not production-grade encryption for backups.
- Reproduction scenario: Create an `.upbak`, flip bytes, and import. The legacy stream had no authenticated integrity boundary.
- Root cause: A reversible compatibility stream was used as the primary package protection.
- Fix implemented: New packages use AES-GCM with a versioned magic header and random nonce. Legacy XOR `.upbak` packages remain readable for migration.
- Risk of fix: Requires `cryptography` at runtime, already declared in requirements. Legacy fallback should be removed after a migration window.
- Verification: Added tests proving new packages are AES-GCM wrapped, decrypt correctly, reject wrong keys, and still read legacy packages.

#### Risk: Secrets exposed outside repo history still need rotation
- Area and files: operational secret handling; earlier chat included a Brevo key.
- Severity: High
- Evidence: Local repo secret scan did not find the Brevo key in tracked files, but the key was shared in chat.
- Impact: Any shared key should be treated as compromised regardless of whether it was committed.
- Reproduction scenario: Not code-reproducible; this is an operational exposure.
- Root cause: Real provider credential shared in a working chat.
- Recommended fix: Rotate the Brevo key, update deployment secrets, and invalidate the old key.
- Risk of fix: Temporary email outage if deployment secret is not updated at the same time.
- Verification method: Send OTP in staging after rotation and confirm old key no longer works.

#### Risk: Extension broad host permissions require store and abuse review
- Area and files: `extension/manifest.json`, `extension-firefox/manifest.json`, `extension/background/userscript-manager.js`
- Severity: Medium
- Evidence: The extension needs broad host access for autofill/CAPTCHA/userscripts, and the userscript manager contains explicit exclusions and browser API registration.
- Impact: Broad permissions increase user trust burden and browser store review risk.
- Reproduction scenario: Install extension and inspect permission prompt.
- Root cause: Product capability requires site-wide automation.
- Recommended fix: Keep permission justification in release docs, prefer host exclusions for high-risk domains, and review every new content/userScript capability against the no-secrets-to-page rule.
- Risk of fix: Too much restriction can break primary workflows.
- Verification method: Browser smoke test across supported sites and verify no secrets enter page context.

### UI/UX Designer

#### Fixed: Payment table displayed corrupted currency/dash text
- Area and files: `frontend/src/app/components/PaymentsPanel.jsx`
- Severity: Low
- Evidence: User-visible strings rendered as mojibake dash and currency symbols.
- Impact: Admin billing screens looked unfinished and reduced trust during payment review.
- Reproduction scenario: Open the admin payments panel with missing timestamp or INR payment data.
- Root cause: Encoding drift in source text.
- Fix implemented: Replaced corrupted text with ASCII-safe `-` and `INR`.
- Risk of fix: Minimal; display-only.
- Verification: Frontend build and contract checks passed.

#### Fixed: Manual payment approval needed stronger operator UX
- Area and files: `frontend/src/app/components/PaymentsPanel.jsx`, `frontend/src/api/billing.js`, `backend/app/api/admin_routes/payments.py`, `backend/app/services/payment_service.py`, `backend/tests/test_razorpay_flow.py`.
- Severity: Medium
- Evidence: Admin approve/reject actions are available for pending payment states, while backend activation can issue subscription/key through an admin override path.
- Impact: A mistaken admin click can grant paid entitlement without Razorpay capture.
- Reproduction scenario: Create a pending order, open payments panel, approve manually.
- Root cause: Admin override exists but the UI does not strongly distinguish override from provider-confirmed settlement.
- Fix implemented: Added a confirmation modal requiring reason text, displays provider/order details, gates the admin API with confirmation/reason, records audit metadata, and appends a payment note.
- Risk of fix: Slower support handling.
- Verification method: Backend Razorpay/admin route tests, frontend build, and frontend contract test passed.

#### Risk: Remaining admin/extension empty/error/loading states need browser QA
- Area and files: `frontend/src/app`, `extension/options`, `extension/popup`
- Severity: Medium
- Evidence: Automated contract/build tests pass, but visual state coverage is not comprehensive.
- Impact: Users may hit confusing screens during failed login, network timeout, expired plan, or extension permission denial.
- Reproduction scenario: Simulate offline server, expired key, failed Razorpay, empty profile, missing userScripts API.
- Root cause: Product has many cross-surface states and limited visual regression coverage.
- Recommended fix: Add a Playwright smoke suite for signup/login, popup account mode, options userscript import, CAPTCHA route management, and billing error states.
- Risk of fix: Test setup cost.
- Verification method: Run Playwright in Chrome and Firefox profiles with fixed screenshots.

### Backend Engineer

#### Fixed: v2 user payload assumed every auth context had email/mobile attributes
- Area and files: `backend/app/api/v2_routes/deps.py`
- Severity: Medium
- Evidence: `user_payload()` accessed `ctx.user.email` and `ctx.user.mobile_number` directly.
- Impact: Legacy/simple user objects could raise `AttributeError`, breaking `/v2/auth/verify-key` and account bootstrap flows.
- Reproduction scenario: Validate a v2 key with a user object missing `email`.
- Root cause: Payload serialization assumed a fully shaped ORM-like user object.
- Fix implemented: Use defensive `getattr` defaults for id, name, email, and mobile.
- Risk of fix: Minimal; preserves fields when present.
- Verification: Existing v2 route tests and full backend suite passed.

#### Risk: Legacy v1/API-key surfaces remain while product direction is email-first
- Area and files: `backend/app/api`, `backend/app/middleware/auth.py`, extension auth compatibility paths.
- Severity: Medium
- Evidence: v1 auth middleware and legacy key validation remain for compatibility.
- Impact: More auth surface area increases maintenance and security review load; user-facing API-key flow may reappear if not carefully hidden.
- Reproduction scenario: Inspect routers/middleware and legacy tests.
- Root cause: Backward compatibility was preserved during the email-login migration.
- Recommended fix: Keep compatibility internally until active users migrate, but add a deprecation flag/date, remove UI exposure, and document allowed legacy endpoints.
- Risk of fix: Premature removal could break existing installs.
- Verification method: Migration test with old key/device and new email login.

#### Fixed: Python dependency audit was missing and vulnerable pins were present
- Area and files: `backend/requirements.txt`.
- Severity: Medium
- Evidence: The first environment audit found vulnerable package versions; requirements did not include a reproducible audit tool.
- Impact: Python vulnerable dependency detection was manual or absent.
- Reproduction scenario: Run `python -m pip_audit` before the fix; vulnerable installed packages were reported.
- Root cause: Security audit tooling and fixed dependency pins were not part of the backend requirement set.
- Fix implemented: Added `pip-audit` and upgraded FastAPI/Starlette, cryptography, Pillow, Jinja2, python-dotenv, python-multipart, requests, idna, and urllib3 constraints.
- Risk of fix: Framework/dependency upgrades can introduce compatibility changes, so backend tests were rerun after installing the upgraded set.
- Verification method: `python -m pip_audit -r backend\requirements.txt` reported no known vulnerabilities; full backend suite passed.

### Frontend Engineer

#### Fixed: Admin refresh hook could mislead future development
- Area and files: `frontend/src/app/hooks/useAdminData.js`, `frontend/src/app/context/AdminDataContext.jsx`.
- Severity: Low
- Evidence: The hook returns `{ loading: false, refresh: () => {} }` while panels fetch their own data.
- Impact: Future screens may rely on a hook that does not actually refresh or track state.
- Reproduction scenario: Import the hook expecting real admin data loading.
- Root cause: Earlier architecture shell remained after panel-level fetch refactor.
- Fix implemented: Converted it to a real refresh-version signal and exposed that through admin context while preserving panel-owned data fetching.
- Risk of fix: Low if usage is checked first.
- Verification method: `rg "useAdminData"` and frontend build.

#### Fixed: Node ESM warning in extension/security scripts
- Area and files: root package configuration and `scripts/*.mjs`
- Severity: Low
- Evidence: Node emitted `MODULE_TYPELESS_PACKAGE_JSON` warnings while running `.mjs` checks.
- Impact: Slower script startup and noisy CI logs.
- Reproduction scenario: Run `node scripts/eaz-sec-001.test.mjs`.
- Root cause: Package type/module configuration mismatch.
- Fix implemented: Added root package metadata, `"type": "module"`, and npm test scripts while keeping CommonJS scripts as `.cjs`.
- Risk of fix: Adding `"type": "module"` can break CommonJS scripts if present.
- Verification method: `npm run test:security`, `npm run test:extension`, and `npm run test:ui` passed.

### End-User Experience Tester

#### Risk: Signup and billing need live browser/payment staging validation
- Area and files: extension popup/options, backend v2 auth/billing routes, frontend payments panel.
- Severity: High for launch readiness, Medium for code integrity.
- Evidence: Automated tests cover route behavior, but a real end-to-end flow requires extension install, email delivery, Razorpay checkout, webhook callback, credit refresh, and extension entitlement refresh.
- Impact: Users could be blocked by provider config, cookie/CORS, popup state, or webhook networking despite passing unit tests.
- Reproduction scenario: Fresh browser profile, install extension, sign up with supported email, verify OTP, purchase plan, solve a CAPTCHA, sync backup.
- Root cause: Multi-service workflow cannot be fully proven by unit tests.
- Recommended fix: Run a staging checklist with real Brevo sandbox/live sender and Razorpay test mode over public HTTPS.
- Risk of fix: Requires provider credentials and staging environment.
- Verification method: Record order ID, payment ID, webhook event ID, subscription status, credit usage, and extension account state.

### Payment and Billing Engineer

#### Verified: Razorpay signature and amount/currency checks exist
- Area and files: backend Razorpay routes/services/tests.
- Severity: Positive finding
- Evidence: Billing route tests pass; docs and code paths include order creation, payment verification, webhook signature validation, amount/currency validation, and idempotency handling.
- Impact: Core billing integrity model is directionally sound.
- Verification: `backend/tests/test_razorpay_flow.py` passed as part of full backend suite.

#### Risk: Manual admin approval is powerful and should be policy-gated
- Area and files: admin payment approval route and `PaymentsPanel.jsx`
- Severity: Medium
- Evidence: Admin approval activates payment/subscription through service logic.
- Impact: Billing can be bypassed by privileged operator action; this may be intended for support but must be auditable and hard to trigger accidentally.
- Reproduction scenario: Admin approves a pending payment without provider capture.
- Root cause: Support override and normal payment review are close in the UI.
- Recommended fix: Require explicit reason, confirmation, role permission, and audit trail display for manual overrides.
- Risk of fix: Adds friction to support.
- Verification method: Test that provider-unverified payment cannot be silently activated.

### Senior Architect and Engineering Manager

#### Risk: Backup/encrypted sync architecture has two different trust models
- Area and files: `extension/lib/crypto-utils.js`, `backend/app/services/sync_service.py`, `backend/app/services/backup_service.py`
- Severity: Medium
- Evidence: Extension sync is end-user encrypted before upload; backend backup packages are server-side protected for operational export/import.
- Impact: Operators may assume all backups are end-to-end encrypted. They are not the same flow.
- Reproduction scenario: Compare sync push/pull blob handling with backend backup export.
- Root cause: Product combines user-owned encrypted sync and admin-owned operational backup.
- Recommended fix: Document this explicitly in admin UI and docs: user sync blob is user-key encrypted; backend backup is server-encrypted operational data.
- Risk of fix: Messaging clarity only.
- Verification method: Docs and UI copy review.

## 3. Cross-Functional Workflow Review

### Authentication and authorization
Email OTP flow now rejects unsupported domains, requires name, checks email delivery availability, rate-limits OTP issuance, and drops stale same-email challenges. v2 authenticated routes rely on dependency validation. v1/API-key compatibility remains and should be formally deprecated rather than silently removed.

### User onboarding
The intended direction is email-first signup/login in the extension popup. Remaining live QA must validate default light mode, field borders in dark mode, OTP delivery, failed OTP retry, plan display, and account refresh after payment.

### Main product workflow
Autofill, CAPTCHA, and userscript workflows are split between extension UI, background workers, content scripts, and backend entitlements. The core security boundary is correct: the extension must not trust local credit cost or expose secrets to pages. Manual browser testing is still required for real userscript import and CAPTCHA solve behavior.

### Admin workflow
Admin dashboard has functional panels and API client protections. Payment operations and backup operations are the most sensitive admin workflows. Manual payment approval should receive stronger confirmation and audit UX.

### Payment and billing lifecycle
Backend-owned plan/credit rules, Razorpay signature verification, webhook idempotency, amount/currency checks, and activation service are present. Remaining launch blocker is staging proof with real Razorpay test mode and webhook delivery over public HTTPS.

### API and database flow
Service-layer tests cover credits, user keys, sync, plans, Razorpay, and middleware. Python dependency vulnerability auditing is missing from the local toolchain.

### Error and recovery paths
Rate limit, failed OTP delivery, failed CAPTCHA quota, backup import, and sync entitlements have tests. Visual QA for user-facing error states remains incomplete.

### Deployment and operational flow
Docker and runtime-data docs exist. Runtime data must stay outside git. Backup cloud mirroring should be verified in staging with actual configured rclone/cloud target.

## 4. Prioritized Implementation Backlog

### P0 - Launch blockers

#### Rotate exposed Brevo key
- Scope: Replace the Brevo key that was shared in chat and update deployment secret storage.
- Files/modules: Deployment secrets, provider dashboard, server env.
- Dependencies: Brevo admin access.
- Acceptance criteria: Old key revoked; OTP email works with new key.
- Verification steps: Send OTP in staging and confirm old key fails.

#### Run live Razorpay staging checkout and webhook
- Scope: Full order/create checkout/verify/webhook/subscription/credit refresh.
- Files/modules: Backend billing routes/services, frontend billing UI, extension account refresh.
- Dependencies: Public HTTPS staging URL and Razorpay test credentials.
- Acceptance criteria: Payment cannot activate without valid signature or explicit audited override; webhook is idempotent.
- Verification steps: Record order/payment/webhook IDs and inspect subscription/credit state.

### P1 - Major functional/security/user-experience problems

#### Move OTP issue quota to shared Redis/backend store
- Status: Completed in code.
- Scope: OTP issuance now uses the existing `RateLimiter` service when available, which is Redis-backed when Redis is enabled and falls back to memory otherwise.
- Files/modules: `backend/app/api/v2_routes/auth.py`, `backend/tests/test_v2_eazyfill_routes.py`.
- Dependencies: Redis must still be enabled in production deployment for cross-replica enforcement.
- Acceptance criteria: The auth route calls the shared limiter for client and identifier scopes, blocks when denied, and does not send email on denial.
- Verification steps: Focused v2 auth tests and full backend suite passed.

#### Add manual payment override confirmation and reason
- Status: Completed in code.
- Scope: Manual admin approval requires explicit confirmation and a reason, records audit metadata, and appends a payment note. Razorpay verify/webhook automation is unchanged.
- Files/modules: `backend/app/api/admin_routes/payments.py`, `backend/app/services/payment_service.py`, `frontend/src/api/billing.js`, `frontend/src/app/components/PaymentsPanel.jsx`, `backend/tests/test_razorpay_flow.py`.
- Dependencies: None beyond existing admin auth/audit service.
- Acceptance criteria: Admin cannot manually approve without confirmation/reason; valid manual override activates through the existing service and records reason.
- Verification steps: Razorpay/admin route tests, frontend build, frontend contract test.

#### Complete browser E2E smoke suite
- Status: Completed as a runnable harness/checklist.
- Scope: Existing Playwright-based extension QA harness is exposed via npm, and staging checklist documents signup, login, options, popup, userscript import, CAPTCHA route, sync backup, billing, and provider checks.
- Files/modules: `package.json`, `scripts/eazyfill_extension_qa.cjs`, `docs/qa/eazyfill_staging_smoke_checklist.md`.
- Dependencies: Staging backend URL, Chrome/Edge, provider credentials for live payment/email sections.
- Acceptance criteria: `npm run test:e2e:extension` runs the extension smoke against `EAZYFILL_QA_API_BASE`; checklist covers live provider proof.
- Verification steps: `npm run test:ui` passed locally; full staging harness remains deployment-time because it needs staging provider config.

### P2 - Maintainability, performance, accessibility, reliability

#### Add Python dependency security scan
- Status: Completed in requirements and verified.
- Scope: Added `pip-audit` and upgraded vulnerable Python dependency pins.
- Files/modules: `backend/requirements.txt`.
- Dependencies: Release/CI should run `python -m pip_audit -r backend\requirements.txt`.
- Acceptance criteria: Requirements-file audit reports no known vulnerabilities.
- Verification steps: `python -m pip_audit -r backend\requirements.txt` passed.

#### Clean remaining mojibake in comments/logs/docs
- Status: Completed.
- Scope: Replaced corrupted punctuation in backend config comments, backup-service rclone messages, and audit text.
- Files/modules: `backend/app/core/config.py`, `backend/app/services/backup_service.py`, this audit report.
- Dependencies: None.
- Acceptance criteria: the mojibake scan has no user-visible hits.
- Verification steps: `rg -n "mojibake scan pattern"` returned no matches in source/docs.

#### Remove or implement `useAdminData`
- Status: Completed.
- Scope: Replaced the no-op hook with a real refresh-version signal and exposed it through admin context.
- Files/modules: `frontend/src/app/hooks/useAdminData.js`, `frontend/src/app/context/AdminDataContext.jsx`.
- Dependencies: None.
- Acceptance criteria: No misleading stub remains.
- Verification steps: Frontend build and contract test passed.

#### Resolve Node module type warning
- Status: Completed.
- Scope: Added root package metadata, scripts, and `"type": "module"` while keeping CommonJS QA scripts as `.cjs`.
- Files/modules: `package.json`.
- Dependencies: None.
- Acceptance criteria: Node test scripts run without module warnings.
- Verification steps: `npm run test:security`, `npm run test:extension`, and `npm run test:ui` passed.

### P3 - Optional polish
- Completed: optional UI snapshot mode was added to the focused UI smoke via `EAZYFILL_UI_SNAPSHOT_DIR`.
- Completed: staging checklist now explains user encrypted sync versus server operational backup.
- Completed: staging checklist now includes browser-store permission review points for broad host permissions.

## 5. Implementation Completed During This Audit

### OTP issuance protection
- Changed files:
  - `backend/app/api/v2_routes/auth.py`
  - `backend/tests/test_v2_eazyfill_routes.py`
- What changed: Added public OTP registration throttling by identifier and client, ensured quota is only consumed after email/dev OTP availability is known, and replaced outstanding same-email challenge on new OTP generation.
- Business logic preserved: Email OTP signup remains the login path; supported-domain and required-name rules remain.
- Verification: Focused auth tests passed; full backend tests passed.

### Backup package encryption
- Changed files:
  - `backend/app/services/backup_service.py`
  - `backend/tests/test_backup_service_remote_config.py`
- What changed: New `.upbak` packages use AES-GCM with versioned magic header and random nonce. Legacy packages remain readable.
- Business logic preserved: Backup/export/import APIs and retention behavior are unchanged.
- Verification: Backup service tests passed; full backend tests passed.

### v2 user payload robustness
- Changed files:
  - `backend/app/api/v2_routes/deps.py`
- What changed: Defensive payload serialization with `getattr` defaults.
- Business logic preserved: Existing payload fields remain when present.
- Verification: v2 route tests and full backend tests passed.

### Payment panel text cleanup
- Changed files:
  - `frontend/src/app/components/PaymentsPanel.jsx`
- What changed: Replaced corrupted currency/dash display with `INR` and `-`.
- Business logic preserved: Display-only change.
- Verification: Frontend build and contract checks passed before final backend rerun.

### Shared OTP limiter
- Changed files:
  - `backend/app/api/v2_routes/auth.py`
  - `backend/tests/test_v2_eazyfill_routes.py`
- What changed: OTP registration now uses the existing Redis-capable `RateLimiter` service when available, with memory fallback only for minimal/test containers.
- Business logic preserved: OTP signup behavior and supported email rules remain unchanged.
- Verification: Focused v2 auth limiter tests and full backend suite passed.

### Manual payment override hardening
- Changed files:
  - `backend/app/api/admin_routes/payments.py`
  - `backend/app/services/payment_service.py`
  - `backend/tests/test_razorpay_flow.py`
  - `frontend/src/api/billing.js`
  - `frontend/src/app/components/PaymentsPanel.jsx`
- What changed: Admin manual approval now requires a confirmation flag and written reason, records audit metadata, and appends a payment note. Automated Razorpay verify/webhook flows remain unchanged.
- Business logic preserved: Payment activation still uses the existing payment service; only the manual admin route is gated.
- Verification: Razorpay/admin payment tests, frontend build, and contract checks passed.

### QA, dependency, and cleanup work
- Changed files:
  - `backend/requirements.txt`
  - `package.json`
  - `scripts/eaz-ui-001.test.mjs`
  - `docs/qa/eazyfill_staging_smoke_checklist.md`
  - `frontend/src/app/hooks/useAdminData.js`
  - `frontend/src/app/context/AdminDataContext.jsx`
  - `backend/app/core/config.py`
  - `backend/app/services/backup_service.py`
- What changed: Added reproducible Python dependency audit tooling and fixed vulnerable pins; exposed root npm QA scripts; added optional UI snapshots; documented staging smoke checks, backup/sync trust models, and permission review; replaced the no-op admin data hook; cleaned remaining mojibake.
- Business logic preserved: No product workflow was removed.
- Verification: Backend tests, frontend build/contract, JS smoke/security scripts, package audit, npm audits, and pip-audit requirements scan passed.

## 6. Final Production Readiness Report

### Completed fixes
- Public OTP issuance throttling and latest-challenge handling.
- OTP issuance throttling now uses the shared Redis-capable limiter when configured.
- Auth payload robustness for partially shaped user objects.
- Authenticated AES-GCM protection for new backend backup packages.
- Admin payment table display cleanup.
- Manual admin payment approval confirmation/reason/audit note.
- Python dependency vulnerability fixes and requirements audit.
- Root npm QA scripts and optional extension UI snapshot capture.
- Staging smoke checklist for extension, payment, email, backup/sync, and browser permissions.

### Remaining risks
- Exposed Brevo key should be rotated before production.
- Razorpay checkout/webhook needs live staging proof.
- Redis must be enabled in production for OTP throttling to be shared across replicas.
- Browser extension permission and userscript workflows still require real Chrome/Firefox release QA against staging.

### Security status
Conditional. Core patterns are sound, dependency audit is clean against requirements, and the highest-risk code issues found in this pass were fixed locally, but secret rotation and live provider validation remain required.

### Billing integrity status
Conditional. Razorpay tests pass, backend-owned entitlement logic exists, and manual override is now gated by confirmation/reason. Live staging reconciliation remains before launch.

### User-experience status
Conditional. Admin UI has improved and local extension UI smoke passes. Full live extension smoke still needs staging backend/provider configuration.

### Test and build results
- `python -m pytest backend\tests`: 148 passed, 13 warnings.
- `python -m compileall -q backend\app backend\migrations`: passed.
- `npm.cmd run build` in `frontend`: passed.
- `npm.cmd run test:contract` in `frontend`: passed.
- `npm.cmd run test:security`: passed.
- `npm.cmd run test:extension`: passed.
- `npm.cmd run test:ui`: passed.
- `powershell -ExecutionPolicy Bypass -File scripts\package_eazyfill_extension.audit.tests.ps1`: passed.
- `npm audit --omit=dev` at root: 0 vulnerabilities.
- `npm audit --omit=dev` in `frontend`: 0 vulnerabilities.
- `python -m pip_audit -r backend\requirements.txt`: no known vulnerabilities found.

### Deployment risks
- Runtime secrets and data mounts must be verified in the actual production compose/environment.
- Backup cloud mirroring requires a real configured target test.
- Provider callbacks need public HTTPS staging verification.
- Extension store review may focus on broad host permissions and userscript capability.

### Final recommendation
CONDITIONAL GO.

The project is not a NO-GO after these fixes, but it should not be treated as final production-ready until the P0 operational tasks are completed: rotate the exposed email key, prove Razorpay staging end to end, and run the browser-extension smoke suite against a staging backend.
