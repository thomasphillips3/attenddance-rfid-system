# AttenDANCE — Feature Roadmap

Client: LaShelle's School of Dance
Status: Phase 1 shipped + Square integration + recurring billing. Building Phase 2.

---

## Phase 1: Billing & Balance Ledger  ✅ DONE
> "Can it show charges/balances like a spreadsheet format that keeps a tally?"

- [x] **1a.** Transaction type field: charge vs payment
- [x] **1b.** Student ledger page with running balance
- [x] **1c.** Payments page with balance overview + Add Charge / Add Payment
- [x] **1d.** Bulk charge tool — charge entire class at once
- [x] **1e.** Recurring auto-billing — set monthly charge rules per class
- [x] **1f.** Square invoice integration — send Pay Now links to parents

## Phase 2: Parent Login
> "Parent login?"

Parents need to see their own kid's info — attendance, balance, profile. NOT edit it.

- [ ] **2a.** Add `role` field to User model: `admin`, `teacher`, `parent`
- [ ] **2b.** Parent-student linking (a parent User is linked to 1+ Students)
- [ ] **2c.** Parent dashboard — read-only view of:
  - Their child's attendance history
  - Their balance / payment history
  - Student profile info (school, allergies, emergency contact)
- [ ] **2d.** Parent registration flow
  - Admin generates invite link or code
  - Parent signs up, gets linked to their kid(s)
- [ ] **2e.** Lock down existing routes — parents can't see other students or admin pages

## Phase 3: Rules & Regulations Acknowledgment
> "Before people register for class, they have to read our rules and regulations and initial each one"

Not a single waiver signature — each rule gets individually initialed.

- [ ] **3a.** Rule model — admin creates individual rules (text + order)
- [ ] **3b.** Acknowledgment flow — parent sees each rule, initials each one (type initials + checkbox)
- [ ] **3c.** Acknowledgment status on student profile — complete / incomplete / expired
- [ ] **3d.** Admin view — manage rules, see who hasn't acknowledged, block enrollment until complete
- [ ] **3e.** Tie to parent login — parents complete this during registration or on first login

## Phase 4: Square Online Payments (enhance)
> "What about if people want to pay with a credit card?"

Square integration is built (Phase 1f). This phase enhances it.

- [ ] **4a.** Auto-record payments — webhook from Square updates ledger when invoice is paid
- [ ] **4b.** Payment status on ledger — show "Invoice Sent" / "Paid via Square" tags
- [ ] **4c.** Batch invoicing — send invoices to all students with balances at once

## Phase 5: Email & Text Blasts
> "There's also an option that lets us email or text blast everyone or whomever we choose"

Send messages to all parents or a filtered group.

- [ ] **5a.** Message composer — write subject + body, pick recipients (all / by class / individual)
- [ ] **5b.** Email delivery via SendGrid or SES
- [ ] **5c.** SMS delivery via Twilio
- [ ] **5d.** Message history — what was sent, to whom, when

---

## Priority Order

**Phase 2 next** — parent login is the most-requested feature and unlocks Phase 3.
Phase 3 after — rules acknowledgment ties into parent registration.
Phase 4-5 are enhancements — build when core features are solid.
