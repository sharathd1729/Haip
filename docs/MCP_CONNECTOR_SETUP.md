# HAIP MCP Connector Setup

Connect Claude (or another MCP-compatible AI assistant) to your HAIP
workspace, so it can read leads, conversations, calls, and bookings, and —
with your confirmation — take real actions like moving a lead's stage or
sending an approved WhatsApp draft.

Reference: `HAIP_MCP_Connector_Plan.md` for the full security model this
setup relies on.

---

## 1. Who can do this

MCP access is currently limited to **Owner** and **Manager** roles — both
issuing tokens and using them. This is a deliberate, temporary restriction
(see the plan's §1.1) that stays in place until HAIP's capability registry
has been in production long enough to widen it to more roles.

## 2. Create an access token

1. In HAIP, go to **Settings → External Assistant Access**.
2. Click **New Token**, give it a name (e.g. "Claude Desktop"), and pick an
   expiry (defaults to 90 days).
3. Before creating it, the dialog shows **what this token can do** — the
   exact set of capabilities your own role has (a token can never do more
   than the user who created it).
4. Click **Create Token**. Copy the **access token** and the **MCP endpoint
   URL** shown — the token is shown exactly once and cannot be retrieved
   again. If you lose it, revoke it and create a new one.

## 3. Configure your client

### Claude Desktop / Claude Code (`.mcp.json`)

```json
{
  "mcpServers": {
    "haip": {
      "url": "https://<your-haip-domain>/mcp",
      "headers": {
        "Authorization": "Bearer <paste-your-token-here>"
      }
    }
  }
}
```

Replace `<your-haip-domain>` with the MCP endpoint URL shown in the token
dialog (it already has `/mcp` on the end), and `<paste-your-token-here>`
with the token you copied in step 2.

### Perisclaw

Add a custom connector, pasting the same MCP endpoint URL and access token.
Perisclaw will prompt for confirmation before any real action (sending a
message, moving a lead, adding a note) — reading data doesn't need
confirmation.

## 4. What to expect

- **Reads never need confirmation.** Listing leads, calls, bookings,
  reading a conversation thread, etc. run immediately.
- **Writes always need confirmation.** Moving a lead's stage, adding a
  note, assigning a lead, approving a draft, or adding a guest signal all
  require the assistant to explicitly confirm with you first — this is
  enforced server-side (`confirm: true` + a unique action key), not just a
  client-side courtesy.
- **Guest phone numbers and emails are masked by default** everywhere the
  assistant can see them (e.g. `+919•••••••10`). If the assistant needs the
  real number — say, to actually call a guest — it has a separate
  `reveal_guest_contact` tool that only works if your role has that
  specific permission, and every use of it is logged to the Compliance
  Center individually (`mcp.pii.reveal`).
- **Guest-authored text is flagged as untrusted.** Message bodies and call
  transcripts come wrapped with a warning that the assistant should treat
  them as data, not instructions — this reduces (but doesn't eliminate)
  the risk of a guest message trying to manipulate the assistant into
  taking an action it shouldn't.
- **No tool can message a guest directly on the assistant's own
  initiative.** The only guest-facing action available is approving an
  *already-drafted* AI reply that a HAIP concierge would otherwise have
  approved by hand.
- **Every tool call is audited**, viewable in **Compliance Center → Audit
  log** — click the **MCP activity** filter chip to see exactly what the
  assistant did, per user, per day.

## 5. What each role can access today

Since only Owner and Manager can use MCP at all right now, and those two
roles differ on very few capabilities, most tools behave identically for
both. Owners additionally have the free-form **Ask HAIP** analyst tool and
can edit the permission matrix itself (**Settings → Roles & Permissions**).

## 6. Revoking access

Go to **Settings → External Assistant Access** and click **Revoke** next
to the token. This takes effect immediately — the next request with that
token is denied. If a team member with an active token leaves the company
or changes role, revoke their token(s) as part of offboarding; a demoted
or deactivated user's token is also automatically denied server-side the
next time it's used, but revoking is still the clean, deliberate way to
close it out.

## 7. Troubleshooting

| Symptom | Likely cause |
|---|---|
| "Unauthorized: invalid or revoked token" | Token was revoked, expired, or mistyped. Create a new one. |
| "Unauthorized: MCP access is limited to owner/manager roles" | Your account's role changed since the token was created, or the token was minted for a role that no longer qualifies. |
| A tool you expect to see is missing from the assistant's tool list | Your role (or the token itself, if it was created with narrowed scopes) doesn't have that capability. Check **Settings → Roles & Permissions** (owner only) or ask your workspace owner. |
| A write action is rejected with "call again with confirm: true" | This is expected — the assistant needs to re-send the same call with `confirm: true` and an `idempotency_key`. Most MCP clients handle this automatically as a confirmation prompt. |
