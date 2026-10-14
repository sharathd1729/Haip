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
