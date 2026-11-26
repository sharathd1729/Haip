# WhatsApp flow canvas (SMS9 parity, Nov 2026)

Goal: a drag-and-drop canvas to build WhatsApp bot flows (like SMS9's Flow Builder), on the EXISTING flow storage
(`wa_flows.nodes` / `wa_flows.edges` JSON, model `WAFlow` in `backend/app/api/v1/endpoints/messaging.py`, routes
`/api/v1/messaging/flows*`) and the EXISTING interpreter `backend/app/services/flow_engine.py` (`run_flow`).
No new table. Existing flows (linear, no positions) must keep working and open on the canvas (auto-layout top to bottom).

Real use to cover (Jade, from SMS9): keyword `hi, hello, hey` -> text -> PDF; keyword `wedding, mehndi` -> text -> 3 PDFs;
plus menus: buttons "Villas / Weddings / Corporate" each leading to its own path.

## Stored shape (contract between backend and frontend)

Every node: `{ "id": str, "type": str, "position": {"x": number, "y": number}, ...config }`.
Every edge: `{ "id": str, "from": node_id, "to": node_id, "label": str | null }`.

| type | config | outgoing edges |
|---|---|---|
| `trigger` | `trigger`: `keyword` \| `opt_in` \| `new_inquiry` \| `check_in` \| `check_out`; `keywords`: [str]; `match`: `exact` \| `contains` | one |
| `message` | `content` (text, `{first_name}` allowed) | one |
| `media` | `media_kind`: `image` \| `video` \| `audio` \| `document`; `file_key` (storage key `<tenant>/wa_flows/...`); `filename`; `caption` | one |
| `location` | `latitude`, `longitude` (numbers), `name`, `address` | one |
| `buttons` | `content`; `buttons`: [{`id`, `title` <= 20 chars}] 1..3 | one per button, `label` = `btn:<id>`; optional `label` = `other` for any other reply |
| `list` | `content`; `button_label` <= 20; `rows`: [{`id`, `title` <= 24, `description` <= 72}] 1..10 | one per row, `label` = `row:<id>`; optional `other` |
| `cta_url` | `content`; `button_label` <= 20; `url` (https only) | one |
| `template` | existing fields (unchanged) | one |
| `question` | `content`; `save_as`: `name` \| `email` \| `notes` \| `custom:<key>` | one (taken after the answer) |
| `condition` | existing (`condition`, ...) | `yes` / `no` (existing) |
| `delay` | existing `delay_minutes` | one |
| `action` | existing `action` (`tag_vip`, `create_inquiry`, `notify_agent`, `opt_out`) plus new `add_label` with `label` (any tag text) | one |
| `http` | `method`: `POST` \| `GET`; `url` (https, SSRF-guarded); `body` (text, `{first_name}` `{phone}` allowed) | one |
| `end` | - | none |

`flow.trigger` (column) mirrors the trigger node's `trigger` value (so `_fire_matching_flows` keeps working).

## Waiting for the guest

`buttons`, `list` and `question` send their message, then the run PARKS in `flow_pending_executions` with
`status = "awaiting_reply"`, `node_id` = that node, `resume_at` = now + 24 h (expiry; the delay beat must ignore
`awaiting_reply` rows), `context` holds what it needs. Interactive reply ids are `wfl:<pending_id>:<option_id>`.

On the guest's next inbound WhatsApp message (before keyword replies and before the AI concierge):
- newest non-expired `awaiting_reply` row for that guest wins;
- `buttons` / `list`: match the interactive reply id (or the option title, case-insensitive) -> follow edge `btn:<id>` /
  `row:<id>`; no match -> follow `other` if it exists, else leave the row waiting and let normal handling run;
- `question`: save the text (name -> guest.name, email -> identity_service signal, notes -> the open inquiry's notes,
  custom:<key> -> the open inquiry's `custom_fields[key]`), follow the single edge;
- mark the row `done`; the inbound message is marked handled (no AI draft, no keyword reply) when a flow consumed it.

## Keyword trigger

Inbound WhatsApp text from a guest: active flow with trigger `keyword` whose trigger node keywords match
(`exact` = whole message equals a keyword after trim/lowercase; `contains` = whole-word match) starts `run_flow`.
Order: awaiting-reply resume > keyword flow > existing keyword replies > AI concierge. Once per message.
A flow never starts twice for the same message (idempotent on the message id).

## Sending

Reuse the existing WhatsApp send functions (`backend/app/workers/tasks/send_whatsapp.py` and
`backend/app/services/wa_interactive.py` `InteractiveSpec`). Media by URL: presign the `file_key`
(`media_storage.get_presigned_media_url`, 1 h) so Meta can fetch it. Every send writes the outbound `Message` the
same way `_send_flow_message` does today. Respect the 24 h window like `_send_flow_message` (outside it, a plain
message is skipped and logged; templates still go).

## Upload

`POST /api/v1/messaging/flows/media` (owner/manager): JPEG/PNG <= 5 MB, MP4 <= 16 MB, MP3/OGG/AAC <= 16 MB,
PDF <= 100 MB (WhatsApp limits), magic-byte checked; stored at `<tenant>/wa_flows/<uuid>.<ext>`; returns
`{kind, key, filename, preview_url}`. Saving a flow rejects a `file_key` that is not this workspace's.

## Validation on save (PUT/POST flows)

One trigger node; button/row titles within limits; ids unique; https urls; edges point at existing nodes;
a `keyword` trigger needs at least one keyword. 422 with a plain message otherwise.
