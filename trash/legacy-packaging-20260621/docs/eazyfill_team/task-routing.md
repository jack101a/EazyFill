# EazyFill Team Task Routing

Use this file to pick the smallest useful agent group for a request.

## Common Task Routes

| User Request | Primary Agent | Reviewer | Verification |
| --- | --- | --- | --- |
| "Fix extension load error" | Extension Architect | QA Release Engineer | Manifest parse, extension browser smoke |
| "Improve popup/dashboard" | Popup Dashboard Designer | QA Release Engineer | Options/popup browser smoke |
| "Add a backend endpoint" | Backend Billing Architect | Security Compliance Guardian | Backend tests, extension contract check |
| "Add or modify billing" | Backend Billing Architect | QA Release Engineer | Billing tests, Razorpay/manual test note |
| "Add userscript feature" | Extension Architect | Security Compliance Guardian | `chrome.userScripts` status, GM API smoke |
| "Prepare Chrome Web Store" | Growth Store Launcher | Security Compliance Guardian | Package, permission copy, screenshot checklist |
| "Release candidate" | QA Release Engineer | Team Orchestrator | Full static/package/browser QA |
| "What remains?" | Team Orchestrator | QA Release Engineer | State file update |

## Default Review Rules

- Security reviews anything touching permissions, userscripts, secrets, billing, sync, or CAPTCHA submission.
- QA reviews anything touching extension-process boundaries or release artifacts.
- Backend reviews anything changing API response shape, credits, auth, sync, or payment state.
- UI reviews anything changing popup/options copy, navigation, empty states, or onboarding.

## Minimal Activation Prompts

Use these concise prompts in future work:

- "Activate EazyFill Team Orchestrator and route this task."
- "Activate EazyFill Extension Architect for MV3/runtime changes."
- "Activate EazyFill Popup Dashboard Designer for UI copy and dashboard changes."
- "Activate EazyFill Backend Billing Architect for v2 API or payment changes."
- "Activate EazyFill Security Compliance Guardian for policy/security review."
- "Activate EazyFill QA Release Engineer and run release gates."
- "Activate EazyFill Growth Store Launcher for store listing and launch assets."
