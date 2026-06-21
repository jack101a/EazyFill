# Razorpay Staging Validation

Use this checklist before enabling Razorpay for real customers.

## Preconditions

- Use Razorpay **Test mode** keys only.
- Deploy the app on a public HTTPS staging URL.
- Create a disposable staging user and active plan.
- Set these env vars on the app:

```env
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...
RAZORPAY_ORDER_TOKEN=...
```

## Razorpay Dashboard

In Razorpay Dashboard Test mode:

- Set webhook URL to `https://YOUR-STAGING-HOST/api/webhooks/razorpay`.
- Use the same `RAZORPAY_WEBHOOK_SECRET` as the app.
- Enable at least `payment.captured`, `payment.failed`, and `order.paid`.
- If asked for OTP while setting up test webhooks, Razorpay documents `754081`
  as the default test OTP.

## Automated App Validation

Run from the repo with staging env values loaded:

```bash
python scripts/razorpay_staging_validation.py \
  --base-url https://YOUR-STAGING-HOST \
  --user-id STAGING_USER_ID \
  --plan-id STAGING_PLAN_ID
```

This creates a real Razorpay test order through the app and verifies that the
local payment status endpoint can read it.

To additionally verify signed webhook handling, duplicate delivery idempotency,
and amount mismatch rejection against a disposable staging account:

```bash
RAZORPAY_VALIDATE_ALLOW_SYNTHETIC_CAPTURE=true \
python scripts/razorpay_staging_validation.py \
  --base-url https://YOUR-STAGING-HOST \
  --user-id STAGING_USER_ID \
  --plan-id STAGING_PLAN_ID \
  --synthetic-webhooks
```

Do not run synthetic capture replay against a real customer account.

## Real Checkout Validation

From the admin UI:

1. Open `Subscriptions` → `Users`.
2. Manage the disposable staging user.
3. Select the test plan.
4. Click `Razorpay Order`.
5. Click `Open Checkout`.
6. Pay with Razorpay test-mode card/UPI flow.
7. Confirm the payment becomes approved only after the signed webhook arrives.
8. Replay the same webhook/event and confirm no duplicate subscription/key is created.

Razorpay test mode uses simulated payments; no real money is charged.
