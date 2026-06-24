# EazyFill Submission Checklist

## Verified Artifact Snapshot

- [x] Chrome manifest name/version: `EazyFill` `1.0.0`.
- [x] Firefox manifest name/version: `EazyFill` `1.0.0`.
- [ ] Chrome artifact present: refresh before submission.
- [ ] Firefox artifact present: refresh separately before Firefox distribution.
- [ ] Package audit passes the current ZIP file.

Previous artifact sizes were from an older workspace snapshot and must not be reused for submission.

## Pre-Publication Blockers

- [ ] Approve and publish an EazyFill privacy policy at a public HTTPS URL.
- [ ] Add an approved public support/privacy contact; it is currently TBD.
- [ ] Reconcile the public policy source with `docs/CHROME_STORE_PRIVACY.md`; the existing `docs/privacy-policy.html` still contains legacy branding and unverified retention language.
- [ ] Capture and approve Chrome Web Store screenshots and any promo images.
- [ ] Enter the final public privacy URL and support channel in the store listing.
- [ ] Complete Chrome Web Store privacy practices using `permission_justification.md`.
- [ ] Review store copy, pricing, and billing availability against the production environment.

## Package Validation

- [ ] Rebuild the exact release candidate for Chrome and Firefox.
- [ ] Run `scripts/audit_eazyfill_packages.ps1` against both release ZIP files.
- [ ] Confirm each package contains its manifest, `_locales`, `background`, `content`, `icons`, `lib`, `options`, `popup`, and `userscripts`.
- [ ] Confirm packages exclude private keys, `.env` files, test data, source maps, nested build output, and stale release artifacts.
- [ ] Confirm 16, 32, 48, and 128 px icons are present.
- [ ] Confirm every manifest reference resolves inside the relevant package.
- [ ] Review the package for remote script URLs, inline extension scripts, `eval`, and `new Function`.

## Chrome Manual QA Gate

- [ ] Clean install on the latest stable Chrome release.
- [ ] Confirm existing-account sign-in, new-account setup, invalid OTP, expired OTP, blocked account, expired session, sign-out, and account refresh states.
- [ ] Confirm the generated device is registered and can be removed.
- [ ] Confirm credit balance refresh, quota reached behavior, and failed-request refund behavior.
- [ ] Configure source and target selectors, request a supported CAPTCHA solve, review the result, and confirm target filling.
- [ ] Record, save, edit, and replay a form-filling rule on an approved test page.
- [ ] Enable Chrome `Allow User Scripts`, then import, save, enable, disable, and run a userscript.
- [ ] Export and import local rules, scripts, profiles, selectors, and settings.
- [ ] Enable optional encrypted sync, then test push, pull, conflict, wrong-account/device, and cloud-delete behavior.
- [ ] Load plans, create the configured billing order, and verify pending, approved, failed, and cancelled states.
- [ ] Reload the extension and browser; confirm local state and service-worker wake behavior.

## Firefox Manual QA Gate

- [ ] Install `extension/dist/eazyfill-firefox-v1.0.0.zip` in the target Firefox test environment.
- [ ] Verify permissions, popup, options, email sign-in, selectors, CAPTCHA assistance, form filling, imports/exports, sync, and billing status.
- [ ] Document userscript compatibility or feature gaps in Firefox.
- [ ] Confirm the Firefox data-collection declaration matches observed behavior.

## Launch Sign-Off

- [ ] Review `support_faq.md` against the release candidate and production support process.
- [ ] Record manual QA evidence and known exceptions.
- [ ] Confirm the public URLs resolve without authentication.
- [ ] Obtain final product, privacy, support, and release approval.
