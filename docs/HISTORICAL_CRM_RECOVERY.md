# Historical CRM data and call recordings — inventory plan and next steps

Status 14 Oct 2026. **The Google Drive inventory has not been done**: the Drive connector is not connected in this environment and
cannot be authorised from here. Nothing was read, copied or moved. The steps below start the moment access exists.

## To unblock

Connect the Google Drive connector in your Claude settings (or share the export folder as a ZIP / paste its link and a file list).
Read-only access to the folder holding the LeadSquared and Zoho exports is enough.

## Inventory (run first, read-only)

For every file, record: path, size, format, export source (LeadSquared or Zoho), entity (leads, activities, calls, notes, users),
row count, earliest and latest date (look at created-on and activity-date columns, not the file's modified date), and the columns present.
Output one table, `docs/crm_history_inventory.md` (file name only; no guest data in it).

Questions the inventory must answer:

1. What is the earliest year with data in each source (the 2016–2017 start is a claim to confirm, per entity)?
2. Do the exports carry **call records** with a recording URL or recording id, or only call metadata?
3. How are agents identified (name, email, id) and can they be mapped to current HAIP users?
4. What is the lead source field called and what values does it hold (needed to map into HAIP sources; unknown values stay "Not recorded", never guessed)?
5. Duplicates: same phone across rows and across the two systems.

## Call recordings — likely situation and next steps

| Question | Why it matters |
|---|---|
| Are recording URLs in the export? | If yes: check whether they still resolve (many CRMs expire links on cancellation). Test five per year, from each provider, **before** any bulk download |
| If links are dead or absent | Ask each vendor (LeadSquared, Zoho, and the telephony provider behind it) in writing for a full recordings export and the retention policy; request a deadline, because deletion after contract end is common |
| Where do recordings live? | Often the telephony provider (not the CRM). Identify it from the call records and ask them directly |
| Volume and size | Estimate hours of audio and storage; plan S3 (ap-south-1) with the existing per-tenant KMS key |
| Consent and DPDP | Historic recordings of guests: confirm the lawful basis and retention period with the owner before ingesting; a recording is personal data |

Ingestion path once files exist: land in a quarantine bucket, verify the URL host against the SSRF allow-list rules used by call
ingest, transcribe with the configured provider (cost is per audio hour: get the estimate approved first), link to a guest only by
verified phone through `identity_service`, and mark the call `source=historical_import` so reports can exclude it.

## Not to do

* No bulk import of historical leads into live pipelines: they would swamp Leads 360 and distort every count. Import into a separate
  historical store or a flagged stage that reports exclude.
* No re-labelling of historical sources into HAIP's current list without the mapping table being approved.
