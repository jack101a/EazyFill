# EazyFill AI Agency Team

This folder defines an EazyFill-focused agent team inspired by the `msitarzewski/agency-agents` repository style: each agent is a specialized Markdown profile with frontmatter, mission, workflows, deliverables, and success metrics.

## How To Use This Team

Start with `eazyfill-team-orchestrator.md` for planning, then activate the specialist that owns the current problem.

Recommended flow:

1. Use the Orchestrator to classify the task and assign owners.
2. Use one build owner for implementation.
3. Use one reviewer owner before merge.
4. Use QA and Security for release candidates.
5. Use Launch/Growth only after core flows are verified.

## Roster

| Agent | Use When |
| --- | --- |
| `eazyfill-team-orchestrator.md` | Breaking down project work, assigning owners, keeping scope aligned |
| `eazyfill-extension-architect.md` | MV3 architecture, background/content/userScripts, Chrome/Firefox compatibility |
| `eazyfill-popup-dashboard-designer.md` | Popup, options dashboard, onboarding, interaction design |
| `eazyfill-backend-billing-architect.md` | FastAPI v2 APIs, auth, credits, sync, Razorpay/local billing |
| `eazyfill-security-compliance-guardian.md` | MV3 policy, privacy, script isolation, API-key and payment security |
| `eazyfill-qa-release-engineer.md` | Extension QA, Playwright smoke, packaging, release gates |
| `eazyfill-growth-store-launcher.md` | Chrome Web Store assets, onboarding conversion, positioning |

## Default Assignment Matrix

| Work Type | Primary | Reviewer |
| --- | --- | --- |
| Extension architecture | Extension Architect | Security Guardian |
| Popup/options UI | Popup Dashboard Designer | QA Release Engineer |
| Backend APIs | Backend Billing Architect | Security Guardian |
| Billing/payment | Backend Billing Architect | QA Release Engineer |
| Userscripts | Extension Architect | Security Guardian |
| Release candidate | QA Release Engineer | Orchestrator |
| Store listing | Growth Store Launcher | Popup Dashboard Designer |

## Project Non-Negotiables

- Stay MV3 compliant: no `eval`, no remote arbitrary code outside `chrome.userScripts`.
- Keep EazyFill local-first: user rules, profiles, scripts, and selector data should work without cloud dependency.
- Treat CAPTCHA solve, autofill, userscripts, billing, and sync as separate surfaces with explicit boundaries.
- Verify with syntax checks, manifest parsing, packaging, and extension browser smoke before calling work done.
- Keep manual QA notes honest, especially Chrome `Allow User Scripts`, real CAPTCHA solve quality, Razorpay test checkout, and Firefox install.
