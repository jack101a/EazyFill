# EazyFill Permission and Data Justification

Use this draft when completing browser store permission and privacy fields. Recheck it against the exact release package before submission.

## Permissions

`activeTab`: Supports user-invoked actions on the current tab, including selector picking, CAPTCHA assistance, recording, and form-filling playback.

`storage`: Stores extension settings, the protected account/session record, rules, scripts, profiles, CAPTCHA selectors, credit state, and sync metadata in browser extension storage.

`unlimitedStorage`: Allows larger user-created script, profile, rule, and backup collections to remain local without relying on server storage.

`scripting`: Injects selector, recorder, and form-filling helpers into pages where the user invokes or configures those features.

`alarms`: Schedules account, credit, userscript registration, and sync-related refresh work from the Manifest V3 service worker.

`notifications`: Displays user-visible status for requested extension operations.

`userScripts`: Registers scripts that the user creates, imports, enables, or disables through the browser's User Scripts API. Chrome also requires the user to enable `Allow User Scripts`.

`downloads`: Saves user-triggered local backup exports from the extension.

`webNavigation`: Detects navigation to `.user.js` install URLs so EazyFill can open its own userscript import flow for the user.

## Optional Permissions

`clipboardWrite`: Requested for user-triggered script helpers such as `GM_setClipboard`.

## Host Permissions

`http://*/*` and `https://*/*`: EazyFill supports user-defined match patterns, form rules, and CAPTCHA selectors across sites selected by the user. Content scripts load on matching web pages so the extension can identify configured rules and respond to user commands. EazyFill does not promise unattended automation, and a site can change or prevent an assisted action.

## Chrome Web Store Data Disclosure Draft

- Personally identifiable information: **Yes.** Registration and sign-in process an email address and a required account name for new accounts.
- Authentication information: **Yes.** One-time verification code state, session tokens, account status, and sync secrets are processed. Session/account data is stored in protected local extension storage and sent to the service for authenticated requests.
- Device information: **Yes.** A generated installation/device identifier and user-agent metadata can be associated with an account/session for device management, limits, support, and abuse prevention.
- Financial and payment information: **Yes, limited.** EazyFill stores plan, amount, currency, payment status, and provider transaction identifiers. Payment instruments and checkout credentials are handled by the selected payment provider.
- Web browsing activity: **Yes, limited to feature use.** The current domain can be sent with requested CAPTCHA operations and recorded with usage/security events. EazyFill does not build a general list of browsing history for advertising.
- Website content: **Yes.** User-selected CAPTCHA images or text and related page metadata are sent for requested solves. User-selected element selectors and captured form steps are processed locally and can be included in optional encrypted sync.
- User content: **Yes.** User-created rules, scripts, profiles, CAPTCHA selectors, and settings are stored locally and can be included in an optional encrypted sync blob.
- Usage information: **Yes.** Credit usage, task type, result status, processing timing, model identifier, domain, timestamps, and network/security metadata can be recorded to operate quotas, reliability, support, and abuse controls.

## Data Handling Commitments

- Optional sync encrypts rules, scripts, profiles, CAPTCHA selectors, and settings in the extension before upload. The service stores the encrypted blob plus device, version, size, hash, and timestamp metadata.
- Session tokens are excluded from the sync payload, although session/sync key material and the generated device identifier are used locally to derive sync encryption keys.
- CAPTCHA images or text are sent only when the user invokes or enables the configured assistance flow. They may be processed transiently by the API, queue, worker, and in-memory duplicate-result cache.
- Billing uses Razorpay-backed order creation, signed payment verification, and webhook reconciliation.
- EazyFill does not sell user data or use it to build advertising profiles.
- Final production retention periods and the public privacy/support contact must be documented before publication.
