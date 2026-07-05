# Auto-Pay / Cards-on-File — Scope & Recommendation

The one remaining Jackrabbit parity gap. This is the decision-ready analysis so
you can greenlight, defer, or descope it. **It is not built** — auto-pay moves
real money against saved cards, so it needs your go-ahead and a live Square
account to build and test safely.

---

## What it is

Families save a card once; the studio auto-charges tuition on a schedule instead
of chasing manual Zelle/Cash App payments. This is Jackrabbit's headline billing
feature and the only capability this system still lacks.

## Why it's well-positioned (most of the plumbing already exists)

- **Square customer handling** — `square_service._find_or_create_customer(email, name)`
  already creates/finds a Square Customer. Cards attach to a Customer.
- **The recurring scheduler exists** — `RecurringCharge` (class/amount/category/
  `day_of_month`) + `_process_recurring_charges()` already run monthly on startup
  and are idempotent. Today they create a *charge* row; auto-pay adds "also
  collect it from the card on file."
- **Square v44 SDK is wired** (`client.customers/orders/invoices/locations`) and
  credentials + encryption-at-rest are in place.

So auto-pay is mostly **card storage + charging**, not a from-scratch integration.

## What has to be built

1. **Card capture (frontend, PCI-safe).** Add Square's **Web Payments SDK** to the
   parent portal. Card details are tokenized in the browser and **never touch our
   server** — we only receive a single-use token. This keeps us out of PCI scope.
2. **Save the card.** New endpoint: token → `client.cards.create` (Cards API,
   linked to the family's Square Customer) → store the returned `card_id` (a
   token, not card data) on a new `SavedCard` model (family_id, square_card_id,
   brand, last4, exp, autopay_enabled). Encrypt nothing sensitive is stored —
   `card_id` is a reference, but treat it as a secret anyway.
3. **Charge on schedule.** Extend `_process_recurring_charges()`: when a charge is
   due and the family has `autopay_enabled` with a saved card, call
   `client.payments.create(source_id=card_id, customer_id, amount)`, and on
   success record a `payment` Transaction (reusing the existing ledger). Keep the
   current idempotency guard so a restart can't double-charge.
4. **Failure handling.** Declined/expired card → record nothing, flag the family,
   email them + the studio, and fall back to the existing manual flow. Never
   silently drop or retry-loop a charge.
5. **Parent + admin UI.** Parent: "Save a card / enable autopay / remove card" on
   the portal. Admin: see which families are on autopay, a per-run result summary
   (charged / failed), and a manual "charge now" for a saved card.
6. **Receipts + audit.** Email receipt on success (email path already exists);
   `AuditLog` every auto-charge.

## Security / compliance

- **PCI:** using the Web Payments SDK (browser tokenization) keeps card data off
  our servers → **SAQ-A**, the lightest PCI tier. Do **not** accept raw PAN on the
  server.
- Reuse the existing `SameSite=Lax` + Origin-check CSRF defense and the `_staff_only`
  / ownership guards; the new parent card endpoints go in the parent-write allowlist.
- Webhook: subscribe to Square `payment.updated` to reconcile async declines.

## Build phases (rough effort)

| Phase | Work | Est. |
|---|---|---|
| 1 | `SavedCard` model + migration; card capture UI (Web Payments SDK) + save endpoint | ~1 day |
| 2 | Charge-on-schedule in the recurring processor + failure handling + receipts/audit | ~1 day |
| 3 | Parent/admin UI (manage card, autopay toggle, run summary) + webhook reconcile | ~1 day |
| 4 | Test end-to-end against Square **sandbox** (success, decline, expiry, idempotency), then a controlled live pilot with 1–2 families | ~1 day |

Call it **~3–4 focused days**, gated on a working Square merchant account and
sandbox credentials. The high-risk part is money movement — Phase 4 (sandbox +
piloted rollout) is non-negotiable before charging real families.

## Risks

- **Double-charge / wrong amount** — mitigated by reusing the existing idempotency
  guard and per-charge audit; test explicitly in sandbox.
- **Variable tuition** — amounts differ per family/plan, so use per-charge
  `payments.create` (not fixed Square Subscriptions), driven by our own schedule.
- **Card churn** — expiries/declines need the graceful fallback so a failed
  autopay just reverts to manual, never blocks the family.

## Recommendation

**Fall runs fine without it.** Manual reconciliation + the A/R aging report (built
this pass) cover collection for the fall session. Auto-pay is the biggest
*ongoing* time-saver, not a launch blocker — so the sensible sequence is: **launch
fall on manual, then build auto-pay as the first post-launch project** once the
Square account is live and you can pilot it with a couple of friendly families
before turning it on studio-wide. Greenlight it whenever you're ready and I'll
build it phase by phase.
