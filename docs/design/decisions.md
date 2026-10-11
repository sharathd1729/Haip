# Design decisions log

Newest first. One entry per decision that changes how the UI is built. Rule from `HAIP_UI_Redesign_Plan.md`: when two sources disagree, follow `docs/DESIGN.md`; if it is silent, follow the plan; log the choice here.

## 2026-10-11

**Third-party design skills are not installed; their ideas are applied directly.**
The five repos named in the plan (impeccable, taste-skill, ui-ux-pro-max-skill, emilkowalski/skills, shaders) all install through `npx`, and impeccable additionally installs hooks that run a downloaded program after every UI edit; shaders links a project to an account. Code from unverified third parties running with shell access is a supply-chain risk this project does not take. What we use from them is the *guidance*, written into `docs/DESIGN.md` section 5: ease-out motion, tinted neutrals, fewer nested cards, visible focus, 16px inputs on touch, worst-case data testing, no colour-only meaning. If a skill is wanted later, install it deliberately from a terminal after reading its files, and never its auto-run hooks.

**Verify tokens: one per workspace per channel, hidden by default.**
The single shared Meta webhook verify token was printed on the Integrations page for every user and was identical for WhatsApp and Instagram. Now each workspace/channel has its own, stored encrypted, shown only to an owner on request (logged), rotatable. The old shared token still verifies until `ALLOW_LEGACY_WEBHOOK_VERIFY_TOKEN=false`.

**Dev gallery route is `/dashboard/dev-kit`, not `/_kit`.** In the Next.js app router a folder starting with an underscore is private and cannot be routed.

**Defaults taken for the plan's open decisions** (revisit any time): Dashboard before Inbox; Reports stays an export wizard for now (rename and a separate Insights page decided in Phase 6); dark mode is a launch requirement; white-label stays a requirement (token-only styling); Ratha and Jade both see the redesign first.
