# EazyFill Performance and Artifact Pass

Date: 2026-06-13

## Scope

- Manifest V3 service-worker and content-script startup.
- Popup and options interaction paths.
- Release package size and package-content audit.
- Auth, credits, CAPTCHA, sync, device, and billing request paths.

## Verified Artifact Snapshot

- Chrome: `extension/dist/eazyfill-chrome-v1.0.0.zip` - 180,083 bytes.
- Firefox: `extension/dist/eazyfill-firefox-v1.0.0.zip` - 180,060 bytes.
- Both manifests identify the product as `EazyFill` version `1.0.0`.

These sizes describe the current workspace files, not a permanent store-size promise. Rebuild and remeasure the final release candidate.

## Behavior Notes

- CAPTCHA assistance depends on per-site source and target selectors and a supported image or text payload.
- Form-filling playback uses rules and actions configured or recorded by the user; page changes can require rule updates.
- Optional sync encrypts the selected extension dataset before upload and requires the same compatible key/device context to decrypt it.
- Chrome userscript execution depends on the browser-level `Allow User Scripts` setting.
- The extension requests Razorpay order creation and relies on signed verification or webhook confirmation before billing state changes.

## Manual Benchmark Queue

- [ ] Measure popup open time on latest stable Chrome from a clean install.
- [ ] Measure options first render with at least 100 rules, 50 scripts, and 20 profiles.
- [ ] Measure requested CAPTCHA round-trip using approved real image samples against the production backend.
- [ ] Measure sync push/pull with 1 MB, 5 MB, and 10 MB encrypted blobs.
- [ ] Exercise service-worker wake and retry behavior after browser idle.
- [ ] Run accessibility and link checks on `marketing_site.html`.
- [ ] Install and manually test the Firefox package.

## Publication Blockers

- [ ] Capture and approve store screenshots and promo images.
- [ ] Publish and verify the public privacy-policy URL.
- [ ] Publish and verify the public support channel.
- [ ] Document production retention periods for CAPTCHA processing, operational logs, account records, sync blobs, and billing records.
