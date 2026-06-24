# EazyFill Chrome Web Store Listing Draft

## Store Fields

- Name: EazyFill
- Category: Productivity
- Language: English
- Single purpose: User-controlled assistance for CAPTCHA entry, repeatable form filling, and user-managed scripts.
- Pricing disclosure: Free plan with optional paid plans or credit purchases, subject to the plans available in the service.
- Privacy policy URL: **TBD - pre-publication blocker. Do not submit until a public HTTPS policy URL is approved.**
- Support contact or URL: **TBD - pre-publication blocker. Do not publish without an approved public support channel.**

## Short Description

User-controlled CAPTCHA assistance, reusable form-filling rules, and userscript tools.

## Detailed Description

EazyFill helps users with repetitive browser tasks through three user-controlled tools in one Manifest V3 extension: configured CAPTCHA assistance, reusable form-filling rules, and a userscript manager that uses the browser's User Scripts API where supported.

Users choose the sites, selectors, rules, profiles, settings, and scripts involved. Rules, scripts, profiles, CAPTCHA selectors, and settings are stored in the browser. Optional cloud sync encrypts that selected extension data before upload. The service backend verifies email-based accounts, sessions, devices, plans, and credits, processes requested CAPTCHA content, and supports billing records.

Core features:

- Configure source and target selectors for supported image or text CAPTCHA assistance.
- Record or author reusable form-filling steps and run them on matching pages.
- Manage userscripts with metadata and match patterns.
- Export and import local rules, scripts, profiles, selectors, and settings.
- Optionally sync an encrypted copy of extension data across compatible installations.
- View plan, credit, usage, and billing status.

EazyFill assists with user-selected actions; it does not guarantee that a page, form, script, or CAPTCHA will work. Websites can change selectors or block extension behavior, and users remain responsible for reviewing actions and following each site's rules.

## Privacy Summary

- Account access processes an email address, required account name for new accounts, one-time verification code state, session token, sync secret, and generated device identifier.
- Session/account records, rules, scripts, and profiles use protected local extension storage. Other settings, CAPTCHA selectors, sync metadata, and the generated device identifier are also stored locally.
- Optional sync uploads an encrypted blob containing rules, scripts, profiles, CAPTCHA selectors, and settings. The service also receives sync metadata such as device identifier, blob size, version, hash, and timestamps.
- A requested CAPTCHA solve sends the selected image or text, the current domain, and related request metadata to the service. Usage and security records can include task type, status, timing, model, domain, device/account association, and network metadata.
- Billing records can include plan, amount, currency, status, and provider transaction identifiers. Payment credentials such as card, UPI, or wallet details are handled by the payment provider, not by the extension.
- EazyFill does not sell user data.

See `permission_justification.md` and `../CHROME_STORE_PRIVACY.md` for the full store disclosure draft and publication blockers.

## Screenshot Plan

- [ ] Popup connected state showing credits and module controls.
- [ ] Selector overlay capturing a CAPTCHA source or target field.
- [ ] Recorder panel with captured form-filling steps.
- [ ] Options dashboard showing rules, scripts, sync, and billing.
- [ ] Billing panel showing available plans or credit options.

Required Chrome Web Store image tasks:

- [ ] Capture approved 1280x800 or 640x400 screenshots.
- [ ] Create an approved 440x280 small promo tile if used.
- [ ] Create an approved 920x680 large promo tile if used.

## Review Notes

- Manifest V3 service worker architecture is used.
- User-managed scripts are registered through the browser User Scripts API.
- Broad host permissions support rules, scripts, selectors, and assistance on sites chosen by the user.
- `downloads` supports user-triggered backup exports. `clipboardWrite` is optional and used only for user-triggered script helper actions.
- Chrome users must enable the browser's `Allow User Scripts` setting before managed scripts can run.
- Firefox packaging exists, but Firefox installation and feature behavior remain manual QA blockers.
