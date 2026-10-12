# Design decisions log

Newest first. One entry per decision that changes how the UI is built. Rule from `HAIP_UI_Redesign_Plan.md`: when two sources disagree, follow `docs/DESIGN.md`; if it is silent, follow the plan; log the choice here.

## 2026-10-12

**The five design skills are now installed locally (user-level); how the Owner Command Center used them.**
They sit in `~/.claude/skills` (impeccable, taste-skill, ui-ux-pro-max, emil-design-eng, shaders), which supersedes the 11 Oct "not installed" note for this machine. Nothing was installed or downloaded for this work. Used: impeccable's operate-mode and craft-floor guidance (read directly; its launcher binary is not present and would need a download, so it was not run, and the detector hook was not enabled); ui-ux-pro-max's local chart-domain search (its Python scripts were checked for network and shell use first); emil-design-eng and taste-skill for motion restraint and hierarchy. Not used: shaders (no decorative effect on a data screen), and ui-ux-pro-max's `--design-system` output (a landing-page pattern with a glass style) because `docs/DESIGN.md` section 5 already sets the direction. Spec: `docs/design/owner-command-center.md`.

**Owners and managers land on the Owner Command Center; everyone else keeps the operations view.**
`/dashboard` renders the Command Center for owner and manager and the former Home page for other roles; the former Home page stays reachable at `/dashboard/operations` for everyone. No route was removed. Bookings and Targets links are hidden for roles without `bookings.read` / `revenue.read` by default (display only; the server enforces).

## 2026-10-11

**Third-party design skills are not installed; their ideas are applied directly.**
The five repos named in the plan (impeccable, taste-skill, ui-ux-pro-max-skill, emilkowalski/skills, shaders) all install through `npx`, and impeccable additionally installs hooks that run a downloaded program after every UI edit; shaders links a project to an account. Code from unverified third parties running with shell access is a supply-chain risk this project does not take. What we use from them is the *guidance*, written into `docs/DESIGN.md` section 5: ease-out motion, tinted neutrals, fewer nested cards, visible focus, 16px inputs on touch, worst-case data testing, no colour-only meaning. If a skill is wanted later, install it deliberately from a terminal after reading its files, and never its auto-run hooks.

**Verify tokens: one per workspace per channel, hidden by default.**
The single shared Meta webhook verify token was printed on the Integrations page for every user and was identical for WhatsApp and Instagram. Now each workspace/channel has its own, stored encrypted, shown only to an owner on request (logged), rotatable. The old shared token still verifies until `ALLOW_LEGACY_WEBHOOK_VERIFY_TOKEN=false`.

**Dev gallery route is `/dashboard/dev-kit`, not `/_kit`.** In the Next.js app router a folder starting with an underscore is private and cannot be routed.

**Defaults taken for the plan's open decisions** (revisit any time): Dashboard before Inbox; Reports stays an export wizard for now (rename and a separate Insights page decided in Phase 6); dark mode is a launch requirement; white-label stays a requirement (token-only styling); Ratha and Jade both see the redesign first.
