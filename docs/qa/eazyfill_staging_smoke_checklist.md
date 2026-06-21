# EazyFill Staging Smoke Checklist

Run this before a production release after deployment secrets and provider callbacks are configured.

## Automated Browser Smoke

Use the existing extension QA harness against the staging backend:

```powershell
$env:EAZYFILL_QA_API_BASE="https://staging.example.com"
npm run test:e2e:extension
```

The harness validates:

- Extension service worker loading.
- Options-page email OTP signup/login against the configured backend.
- Profile, autofill rule, userscript, CAPTCHA, sync, and billing screens.
- Autofill playback and recorder capture.
- Userscript URL import and browser `userScripts` behavior when the browser toggle is available.
- CAPTCHA route save plus global fill delay and human typing settings.
- Encrypted sync push/pull and billing plan refresh.

For visual QA snapshots of the mocked extension UI:

```powershell
$env:EAZYFILL_UI_SNAPSHOT_DIR="artifacts/eazyfill-ui-snapshots"
npm run test:ui
```

This captures representative options and popup states for manual visual comparison.

## Payment Smoke

1. Create a Razorpay test order from the user billing flow.
2. Complete a test payment in Razorpay checkout.
3. Verify `/v2/billing/verify-payment` succeeds with a valid signature.
4. Verify the Razorpay webhook receives the event over public HTTPS.
5. Confirm webhook idempotency by replaying the same event ID.
6. Confirm subscription, plan, and credit balance refresh in the extension.

Manual admin approval is a separate support override. It must require a reason and confirmation, and must not be used as the normal Razorpay path.

## Email Smoke

1. Rotate any exposed Brevo key before staging.
2. Send OTP to a supported real provider such as Gmail or Outlook.
3. Confirm temporary domains are rejected.
4. Confirm repeated OTP requests are throttled across deployment replicas when Redis is enabled.

## Backup And Sync Smoke

- Extension sync blobs are end-user encrypted before upload. The server stores opaque encrypted blobs and validates blob hash/size.
- Backend backup packages are server-encrypted operational backups. They are not the same trust model as user sync.
- Confirm `.upbak` export/import with the configured backup key.
- Confirm cloud/rclone mirror upload and retention on the configured remote.

## Browser Permission Review

The extension intentionally requests broad host permissions for autofill, CAPTCHA, and userscripts. Release review should confirm:

- Store listing explains why site access is needed.
- High-risk host exclusions still exist in the userscript manager.
- No API keys, OTPs, sync secrets, or billing secrets are injected into page context.
- Chrome and Firefox packages are generated from clean extension folders only.
