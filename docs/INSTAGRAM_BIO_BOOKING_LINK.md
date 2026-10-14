# Instagram bio booking link — what was verified and what is needed

Status 14 Oct 2026. **Nothing live was changed**: no Razorpay setting, no Instagram bio, no external account.

## What exists today (verified)

| Step | Where | Result |
|---|---|---|
| Connect Razorpay (per tenant keys, encrypted; webhook URL + secret issued) | `POST /payments/razorpay/connect` | Tested (`tests/test_booking_detail.py`, 13 passed) |
| Create a payment link for a booking | `POST /bookings/{id}/payment-links` | Needs an **existing booking** and staff login; amount defaults to the outstanding balance; expires in 1–30 days; audited |
| Guest pays | Razorpay-hosted page | Razorpay's own page, mobile-friendly; not HAIP UI |
| Payment recorded | `POST /webhooks/razorpay/{tenant_slug}` | Signature verified, recorded once (a Razorpay retry returns `duplicate`), unknown tenant/link ignored, other tenant's link never matches |
| Booking shows the payment | booking page ledger | Tested |

## Why it cannot go in the bio as it is

1. A link exists only **after** staff create a booking for a named guest. There is no public page where a visitor picks dates, a package and pays, so a single link for the bio has nothing to point at.
2. Link creation is **not idempotent**: pressing the button twice makes two links for the same balance.
3. A booking is `confirmed` the moment it is created, before any payment; there is no hold that releases if the link expires.

## Options (pick one; none is done)

| Option | What the bio link is | Needs |
|---|---|---|
| A. Enquiry-first (recommended now) | `wa.me` click-to-chat or the existing Instagram DM. Staff or the AI collect dates, the team creates the booking and sends the per-booking Razorpay link | Nothing new; works today |
| B. Fixed advance page | A Razorpay **Payment Page** for a fixed advance (for example the enquiry deposit), created in Razorpay's dashboard | Your authorisation to create it in the live Razorpay account; a rule for matching the payment to a lead (the page does not carry a HAIP booking id) |
| C. Self-serve booking page | New public page: package, dates, availability check, then a Razorpay link created server-side with a hold | Build work: public availability, link idempotency, hold and expiry, conflict check on create. Part of the Sales Agent plan (`docs/ai/SALES_AGENT_PLAN.md`) |

## Before any public link is used

* Make link creation idempotent per booking and amount (return the live link instead of creating another).
* Decide the hold rule (does an unpaid link keep the dates, and for how long).
* Test on a phone, in Razorpay **test mode**, from the bio's in-app browser (Instagram's browser blocks some UPI intents: test UPI and card).
* Only then, with your explicit go-ahead, update the bio.

## Safest practical design for a public booking link (when you decide to build it)

Recommendation: **a public booking REQUEST page, not a public pay-now page.** The visitor never creates a booking or a payment by
themselves; HAIP creates a lead and a priced request, and a payment link only after availability is confirmed.

1. **Page** (public, per tenant slug, phone-first): package, dates, guests, name, phone, consent checkbox (DPDP). Bot protection and a rate
   limit per IP and phone. No card or UPI data is ever entered in HAIP: payment happens on Razorpay's own page.
2. **Server** creates a `booking_request` and a lead (through `identity_service`, source recorded as `website` or a dedicated
   `instagram_bio` value so attribution stays truthful), prices it from published package data (`package_pricing_service.quote`, never from the
   browser), checks availability (`calculator_service.is_open`), and **refuses with a plain reason** when it cannot price or the dates are taken.
3. **Hold**: a short hold on the dates (for example 30 minutes) while the visitor pays; released on expiry. Without a hold two guests can pay for the same dates.
4. **Payment link**: created server-side only after step 2, for the quoted advance, with an **idempotency key** = `booking_request_id + amount`.
   A second call returns the same live link. Razorpay's `reference_id` carries the request id so a link can never be matched to the wrong request.
5. **Payment verification** (the money source of truth is Razorpay, never the browser redirect): the signed webhook (`payment_link.paid`) is the
   only thing that marks a request paid; it must verify the signature, match the link to the request, check **amount and currency equal the quote**, and be
   idempotent on the payment id (already implemented for booking links). A scheduled reconciliation fetches links still unpaid after expiry and
   links paid with no webhook, so a missed webhook never loses a payment.
6. **Booking**: created (or the request confirmed) in one transaction with the payment record; a conflict at that moment (dates taken after the hold
   expired) triggers a human task and a refund decision, never an automatic refund.
7. **Messaging**: confirmations go through the existing consent and opt-out rules; no marketing content in the payment message.

Needed before building: Razorpay live keys connected per tenant (owner), a decision on the hold length and advance rule (payment policy
record), the package prices published, and the Increment-1 items for conflict checks and link idempotency (`docs/ai/SALES_AGENT_PLAN.md`).
Until then Option A (WhatsApp click-to-chat from the bio) is the safe choice and needs no change in Razorpay or Instagram beyond the bio link itself,
which stays untouched until you authorise it.
