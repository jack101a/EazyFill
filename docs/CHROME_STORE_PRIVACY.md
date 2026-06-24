# EazyFill Chrome Web Store Privacy Publication Draft

## Publication Status

**Blocked for publication.**

- Public privacy policy URL: **TBD before publication**
- Public support/privacy contact: **TBD before publication**
- Production retention schedule: **TBD before publication**

Do not enter a fabricated domain, email address, or support URL in the Chrome Web Store.

The existing `docs/privacy-policy.html` is not ready to publish because it contains legacy branding and retention statements that have not been verified against production. The owner of that public policy source must reconcile it with this disclosure draft, add the approved contact, deploy it to HTTPS, and record the final URL here.

## Product and Data Scope

EazyFill provides user-controlled browser assistance for configured CAPTCHA fields, reusable form-filling rules, and user-managed scripts. It does not promise unattended or universal automation. Users choose the sites, selectors, rules, profiles, settings, scripts, and actions involved.

### Account, Authentication, and Device Data

EazyFill can process:

- Email address used for sign-in and registration.
- Required account name for new accounts.
- One-time verification code challenge state.
- Session token, sync secret, account status, plan, subscription, and credit state.
- A randomly generated installation/device identifier.
- Device name, user-agent metadata, first/last-seen timestamps, and device status.

The extension stores the account/session record in protected local extension storage. The generated device identifier is stored in local extension storage and sent with authenticated service requests. The service stores account/session/device associations for access control, device limits, support, and abuse prevention.

### User-Created Rules, Scripts, Profiles, Selectors, and Settings

The extension stores user-created form rules, userscripts, profiles, CAPTCHA selectors, settings, credit state, and sync metadata in browser extension storage. Account/session records, rules, scripts, profiles, and supported userscript storage records use the extension's protected local storage layer; not every local setting or metadata field is encrypted.

This content is used to provide the actions the user configures. Page changes, unsupported frames, browser restrictions, or invalid selectors can prevent an action from working.

### Optional Encrypted Sync

Cloud sync is optional and is disabled by default in the extension settings.

When the user invokes sync, EazyFill creates a payload containing:

- Form-filling rules.
- Userscripts.
- Profiles.
- CAPTCHA selectors.
- Settings, excluding session/authentication fields.
- Sync version metadata.

The extension encrypts that payload before upload using AES-GCM with key material derived from the session/sync secret and generated device identifier. The service stores the encrypted blob and operational metadata including the device identifier, version, blob hash, blob size, and timestamps. The service implementation does not receive the plaintext sync payload, but loss or change of the required account/session/device context can prevent decryption.

Users can request deletion of the cloud sync blob through the extension. The final policy must state the production deletion and backup-retention timing.

### Selected Website Content and CAPTCHA Requests

For configured CAPTCHA assistance, EazyFill can read the user-selected source element and target field. A solve request can send:

- The selected CAPTCHA image encoded for transport, or selected text.
- The current website domain.
- Image dimensions or related request metadata.
- Session/account authentication and generated device identifier in request headers.

The CAPTCHA payload can be processed transiently by the API, an in-process or remote queue, solver workers, and a duplicate-result cache keyed from a hash of the request. Operational usage records can include task type, status, processing time, model identifier, domain, account/key association, IP address, and timestamps.

Do not publish a promise that CAPTCHA payloads are deleted immediately or within a specific period until the production queue, logs, cache, worker, backup, and infrastructure retention settings are documented and approved.

EazyFill does not need a general browsing-history list to provide its features. It does, however, process the current domain and selected page content when a user invokes a configured feature, and those limited web-activity disclosures must be selected in the store form.

### Credits and Usage

The service tracks CAPTCHA usage and quota/credit state to enforce plan limits. A requested solve can reserve a credit; the current API attempts to refund the reservation when processing fails before a result is returned. Usage history and balance information can be displayed in the extension.

Credits, quotas, reset timing, and available plans depend on the account and production plan configuration. Store copy must not promise a fixed allowance unless it matches the live plan catalog.

### Billing and Payment Providers

The extension creates Razorpay-backed orders through the backend. The backend verifies signed Razorpay payment responses and webhooks before reconciling access.

EazyFill billing records can include:

- User/account and plan identifiers.
- Amount and currency.
- Payment method/provider.
- Order, payment, reference, and status identifiers.
- Provider status, signed verification data, webhook payloads, and timestamps.

Payment providers handle payment instruments and checkout credentials such as card, UPI, or wallet details. Their own privacy terms apply when the user enters data into a provider checkout.

### Data Sharing and Sale

EazyFill does not sell user data and does not use it to build advertising profiles.

Data can be disclosed to service providers only as needed to provide hosting, CAPTCHA processing infrastructure, communications, security, support, optional sync, and billing; to comply with law; or to protect users and the service. The final public policy must identify provider categories accurately for the production deployment.

## Chrome Web Store Disclosure Checklist

- [ ] Personally identifiable information: disclose registration/sign-in email and required account name for new accounts.
- [ ] Authentication information: disclose OTP challenge state, session/account state, and sync secret handling.
- [ ] Device information: disclose generated device identifier, device metadata, and user agent.
- [ ] Financial/payment information: disclose purchase, subscription, amount, status, and provider transaction records; explain provider handling of payment instruments.
- [ ] Web browsing activity: disclose current-domain processing tied to configured feature use; do not claim collection of a general browsing-history list.
- [ ] Website content: disclose selected CAPTCHA images/text and selected page elements.
- [ ] User content: disclose rules, scripts, profiles, selectors, settings, and optional encrypted sync.
- [ ] Usage information: disclose credits, quotas, operation status, timing, domain, and security/network metadata.
- [ ] Data sale: answer **No**.
- [ ] Advertising use: answer **No**.
- [ ] Optional encrypted sync: explain local encryption, uploaded metadata, deletion controls, and decryption limitations.

## Required Publication Steps

- [ ] Rebrand and correct the public policy source.
- [ ] Approve production retention periods and provider categories.
- [ ] Add the real public support/privacy contact.
- [ ] Deploy the policy to a public HTTPS URL.
- [ ] Verify the URL without authentication in a clean browser session.
- [ ] Paste the verified URL into the Chrome Web Store privacy-policy field.
- [ ] Save the final URL and approval date in this file.
