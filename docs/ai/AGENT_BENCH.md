# Agent test bench (22 Oct 2026)

Guest scenarios run through the **real** reply pipeline (`concierge_draft`, guards, Ask a manager, agent policy, sales agent) and
are graded **in code**. Two layers share one engine, `backend/app/services/agent_bench.py`:

| Layer | Command | Model | Where |
|---|---|---|---|
| Deterministic | `pytest tests/test_agent_bench.py` | scripted per scenario (`classify`, `reply`) | CI, every PR |
| Live | `python scripts/agent_bench.py --tenant rathaa --live -k 5` | the real LLM router | by hand, inside the API container; never CI |

The deterministic layer pins what code guarantees whatever a model says: triggers fire (consult + reason), no unpublished,
invented or below-floor price is sent (`no_unsupported_figure_sent` runs on every scenario), one holding reply, no payment link,
quote send or booking without approval. The live layer measures the model: each scenario runs k times and passes only if all k
pass (**pass^k**); the report also gives pass@1.

## Scenarios

`backend/tests/fixtures/agent_bench/rathaa.json` (56 scenarios): grounded quotes for the Mysuru 1/2/3-day packages, a below-floor
price, New Year (no published rate -> consult, no price), 10 people overnight, the JLR safari (billed at actuals; an invented
figure is held), self-drive (no), partner/B2B and commission asks, discounts (English, Hinglish, Hindi and Kannada script; policy
autonomous / draft), angry and frustrated guests, "talk to a person", Hindi and Kannada questions (reply language), custom Kerala /
Goa / customised routes, cancellation and refund, off-hours holding text ("by 10 am tomorrow" / "today"), a repeated question,
the third deferred question, two prompt injections, model failure, low confidence, ungrounded availability and photo claims, kit
suggestions, an owner policy that consults on everything, and the sales agent on autopilot waiting for a person before a payment
link. Dates are relative (`{d+N}`, `{peak}`), so the file never goes stale. Add a scenario by copying one; give it `tags` and an
`expect` block (checks: `consult`, `reasons_any`, `auto_sent`, `holding_reply`, `holding_regex`, `no_figure_sent`, `draft_regex`,
`draft_not_regex`, `prompt_contains` (scripted only), `language` (hi / kn), `allow_payment_link`).

## Safety of the live run

The runner points `DATABASE_URL` at a throwaway SQLite file (`--bench-db`, recreated each run) before importing the app, builds
its own world (Rathaa's catalogue published and re-dated to start today, two caravans, the sales playbook), and captures every
send, staff alert, push and SSE event in-process. It never reads or writes a real workspace. Only the model calls leave the
machine. A tenant's own playbook can be benched with `--playbook export.json` (the JSON of `GET /ai/sales-playbook`).

## Comparing a candidate prompt (harness2-style)

1. Run the current prompt: `python scripts/agent_bench.py --live -k 5 --out reports` -> `reports/<stamp>/report.json`.
2. Run the candidate on the same scenarios and k: `python scripts/agent_bench.py --live -k 5 --prompt cand.jinja --compare-with reports/<stamp>/report.json`.
3. `report.md` puts both side by side and prints a verdict: ADOPTABLE only when no scenario's pass^k drops and the overall
   pass^k is not lower. Tone can be compared with `--judge` (an LLM opinion, labelled ADVISORY, never part of pass/fail).
4. Adopt only with the owner's approval: copy the candidate over `app/prompts/concierge_reply.jinja`, bump `concierge_reply` in
   `core/prompt_versions.py` in the same commit, and add scenarios for whatever the change was meant to fix.
