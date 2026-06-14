# HAIP Hospitality Agent — Dograh Workflow Configuration

Configure this workflow in the Dograh dashboard UI at `http://your-dograh-server:3010`.

---

## Workflow Details

- **Name**: HAIP Hospitality Agent
- **Language Model**: Claude (claude-sonnet-4-6)
- **STT Provider**: Sarvam AI (saarika:v2)
- **TTS Provider**: Sarvam AI (bulbul:v1)
- **Language**: Auto-detect (Hindi, English, Kannada, Tamil)

---

## System Prompt

Paste into Dograh's **Start Call** node → System Instructions:

```
You are an AI hospitality concierge for [Property Name].
You speak naturally in the caller's language — Hindi, English, Kannada, or Tamil.

Your job:
1. Greet the caller warmly
2. Understand their inquiry
3. Answer basic questions about the property
4. Collect booking details if they want to book
5. Transfer to a human agent for complex requests

Property details will be injected via the HAIP_PROPERTY_CONTEXT variable.

Rules:
- Keep responses under 30 words (this is a phone call)
- Always confirm you understood before responding
- If unsure: transfer to human agent
- Never make up pricing or availability
- Always be warm and professional

Extract these variables during the call:
- intent: what does the caller want? (booking/availability/complaint/pricing/amenities/directions/other)
- check_in_date: check-in date if mentioned (ISO format)
- check_out_date: check-out date if mentioned (ISO format)
- guest_count: number of guests if mentioned (integer)
- sentiment: caller's emotional tone (positive/neutral/negative)
- language_detected: which language they spoke (hi-IN/en-IN/kn-IN/ta-IN/hi-en)
```

---

## Workflow Nodes

### Node 1 — Start Call (Greeting)

- **Type**: Text-to-Speech
- **Text**: `"Namaste! Welcome to [Property Name]. How can I help you today?"`
- **Language detection**: Auto (detect from first caller utterance)
- **Next**: Node 2 (Intent Detection)

---

### Node 2 — Intent Detection

- **Type**: LLM Classification
- **Prompt**: `"Based on what the caller said, classify their intent: booking / availability / complaint / pricing / amenities / directions / other"`
- **Branches**:
  - `booking` → Node 3A
  - `availability` → Node 3B
  - `complaint` → Node 3C
  - `pricing` → Node 3D
  - `amenities` → Node 3E
  - `directions` → Node 3E
  - `other` → Node 3F

---

### Node 3A — Booking Intent

- **Type**: Conversational
- **Prompt**: `"I'd be happy to help with your booking. Could you tell me your check-in date, check-out date, and number of guests?"`
- **Extract**: `check_in_date`, `check_out_date`, `guest_count`
- **Next**: Node 4 (Collect Details)

### Node 3B — Availability Check

- **Type**: Conversational
- **Prompt**: `"For which dates would you like to check availability?"`
- **Extract**: `check_in_date`, `check_out_date`
- **Next**: Node 4 (Collect Details)

### Node 3C — Complaint

- **Type**: Text-to-Speech
- **Text**: `"I'm sorry to hear that. Let me connect you with our property manager right away."`
- **Set variable**: `transfer_reason = "complaint"`
- **Next**: Node 5 (Transfer to Human)

### Node 3D — Pricing Inquiry

- **Type**: Conversational
- **Prompt**: `"Our pricing varies by season and dates. Could I take your preferred dates to give you an accurate quote?"`
- **Extract**: `check_in_date`, `check_out_date`
- **Next**: Node 4 (Collect Details)

### Node 3E — Amenities / Directions

- **Type**: Conversational
- **Prompt**: `"I'd be happy to help! [Answer from property knowledge base]. Is there anything else I can help with?"`
- **Next**: Node 6 (Wrap Up) or Node 5 if caller wants more help

### Node 3F — Other / Unclear

- **Type**: Text-to-Speech
- **Text**: `"Let me connect you with our team who can better assist you."`
- **Next**: Node 5 (Transfer to Human)

---

### Node 4 — Collect Details

- **Type**: Conversational
- **Goal**: Extract `intent`, `check_in_date`, `check_out_date`, `guest_count`
- **Confirm back to caller**: `"So you're looking for [dates] for [N] guests — is that right?"`
- **Next**: Node 6 (Wrap Up)

---

### Node 5 — Transfer to Human

- **Type**: Call Transfer
- **Set variables**:
  - `transfer_to_human = true`
  - `transfer_reason = [detected intent]`
- **Action**: Transfer to property manager's number (configure per-property)
- **Fallback** (if transfer fails): `"Our team will call you back shortly. Thank you for your patience."`
- **Next**: End Call → Webhook

---

### Node 6 — Wrap Up

- **Type**: Text-to-Speech
- **Text**: `"Thank you for calling [Property Name]. Our team will follow up with you shortly. Have a wonderful day!"`
- **Next**: End Call → Webhook

---

## Webhook Configuration (in Dograh Dashboard)

Configure under **Settings → Webhooks → Add Webhook**:

| Field | Value |
|-------|-------|
| Event | `call.completed` |
| URL | `https://your-haip-server.com/api/v1/webhooks/dograh/{tenant_slug}` |
| Secret | Per-tenant secret (get from HAIP Settings → Voice Platform) |
| Retry | 3 times on failure, exponential backoff |
| Timeout | 10 seconds |

> **Getting your tenant's webhook URL**: `GET /api/v1/settings/voice-platform` returns `webhook_url`.
> Configure Dograh with this URL and the secret generated by HAIP.

---

## Variable Extraction Reference

Dograh will populate these variables and send them in the webhook `extracted_variables` field:

| Variable | Type | Notes |
|----------|------|-------|
| `intent` | string | `booking\|availability\|complaint\|pricing\|amenities\|directions\|other` |
| `check_in_date` | string (ISO date) | YYYY-MM-DD |
| `check_out_date` | string (ISO date) | YYYY-MM-DD |
| `guest_count` | integer | Number of guests mentioned |
| `property_name` | string | Property the caller referenced |
| `sentiment` | string | `positive\|neutral\|negative` |
| `language_detected` | string | BCP-47: `hi-IN\|en-IN\|kn-IN\|ta-IN\|hi-en` |

---

## Per-Property Customization

For each HAIP property (Ratha, Jade, etc.), customize:

1. **System prompt `[Property Name]`**: Replace with actual property name
2. **Transfer number**: Set in Node 5 to property manager's mobile
3. **Knowledge base**: Add property-specific FAQs (amenities, policies, directions)
4. **Greeting language**: Default language based on property location

---

## Testing the Workflow

1. Call your Twilio number
2. Dograh routes the call through the HAIP Hospitality Agent workflow
3. After the call ends, Dograh sends `call.completed` webhook to HAIP
4. Check HAIP dashboard → Leads360 for the new inquiry card
5. Verify transcript appears in the call detail view
