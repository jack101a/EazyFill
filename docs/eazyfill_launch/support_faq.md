# EazyFill Support FAQ and Known Limitations

Public support contact: **TBD - pre-publication blocker**

Do not publish the extension until an approved support channel is available.

## Account Access

### How do I sign in?

Open the EazyFill popup and choose **Sign in / Sign up**. Enter your supported email address. Existing accounts receive a verification code. New accounts are asked for a name, then receive a verification code. After verification, the extension stores an account/session record in protected local extension storage.

### What should I do if sign-in fails?

Confirm that the email address is typed correctly, uses a supported provider, and that the verification code has not expired. If the account is blocked, expired, assigned to too many devices, or cannot receive email, use the approved support process once it is published. Never share a verification code or session details in screenshots or public support posts.

### What is the device identifier?

EazyFill creates a random identifier for the installation and sends it with authenticated requests. The service can associate it with the account/session for device management, limits, support, and abuse prevention. Removing a device from the account can require signing in again on that installation.

## Credits and Quotas

### Why did a CAPTCHA request use a credit?

CAPTCHA requests are metered against the account's configured allowance. The service reserves a credit before processing and reports the remaining balance with the response. The current API attempts to refund a reserved credit when processing fails before a result is returned.

### Why is the displayed balance unavailable or out of date?

The extension caches recent credit state and refreshes it from the service. Check the connection, refresh credits from the popup or options page, and verify that the account is signed in. Plan limits and reset timing come from the service and can differ by account.

## CAPTCHA Selector Setup

### What selectors are required?

Each site configuration needs:

- The site domain.
- A source selector for the CAPTCHA image, canvas, or supported text element.
- A target selector for the field that should receive the returned text.
- The correct task type (`image` or `text`).

Use the selector picker where possible, save the configuration, and test it on an approved page. Selectors are CSS selectors and can stop working when the site changes its markup.

### Why does the picker or solve action not find the CAPTCHA?

Common causes include an incorrect domain, a changed selector, a CAPTCHA inside an unsupported frame, a cross-origin image that cannot be read, a canvas or element type the detector does not support, a disabled module, a signed-out or expired account, no remaining credits, or a site that blocks extension behavior. The selector picker also times out if no element is chosen.

### Does EazyFill bypass every CAPTCHA?

No. EazyFill assists with configured image or text CAPTCHA fields and sends selected content to the service for a requested solve. Accuracy and availability vary by image quality, site behavior, model support, network state, and service capacity. Interactive challenges such as reCAPTCHA, hCaptcha, Turnstile, or behavioral checks are not guaranteed to work. Users must follow the website's terms and applicable rules.

## Form Rules and Userscripts

### Why did a form rule stop working?

Rules depend on page structure, selectors, timing, and the actions recorded or authored by the user. Edit the selector or wait step after a site redesign, and test the rule before relying on it. EazyFill provides user-controlled assistance and does not guarantee unattended completion.

### Why will a userscript not run in Chrome?

Chrome requires the browser-level `Allow User Scripts` setting for extensions that use the User Scripts API. Open EazyFill's extension details in Chrome, enable `Allow User Scripts`, reload the extension and target page, and confirm that the script is enabled and its match patterns include the page.

Imported scripts can access page content permitted by their match patterns and supported helpers. Review script source before enabling it.

## Sync and Backups

### What does encrypted sync include?

An invoked sync includes rules, scripts, profiles, CAPTCHA selectors, and settings. Authentication/session fields are excluded from the payload. Encryption happens in the extension before upload; the service stores the encrypted blob and metadata.

### Why can another installation not decrypt a backup?

The sync key is derived from account/session sync material and the generated device identifier. A different, rotated, or lost account/device context can make the blob unreadable. Keep an exported local backup before replacing an installation. Cloud sync is optional and can be deleted from the extension.

## Billing

### What billing methods are currently supported?

The extension starts Razorpay-backed orders through the backend. Available checkout instruments, such as card, UPI, or wallet, are controlled by Razorpay and the production account configuration.

### Who handles payment details?

Razorpay handles checkout credentials such as card, UPI, or wallet details. EazyFill records plan, amount, currency, order/payment identifiers, and payment status so it can reconcile access after signed verification or webhook confirmation.

### What should I do if payment succeeded but access did not update?

Do not submit another payment immediately. Record the EazyFill payment/order identifier and provider transaction identifier without sharing payment credentials. Refresh billing status, then use the approved support channel once it is published.

## Browser Support and Manual QA

### Is Firefox fully supported?

An EazyFill Firefox `1.0.1` package can be generated from the Firefox extension folder, but Firefox installation and end-to-end feature behavior remain manual QA blockers. Userscript behavior and browser API differences must be tested and documented before Firefox distribution.

### What still requires manual launch verification?

- [ ] Latest stable Chrome clean install.
- [ ] Chrome `Allow User Scripts` and real userscript execution.
- [ ] Real-site selector setup and CAPTCHA quality.
- [ ] Form-rule recording and playback on approved sites.
- [ ] Billing pending/success/failure/cancellation behavior.
- [ ] Encrypted sync push, pull, conflict, deletion, and recovery limitations.
- [ ] Firefox install and full feature matrix.
- [ ] Store screenshots and promo images.
- [ ] Public privacy-policy URL.
- [ ] Public support/privacy contact.
