# AttenDANCE — Feature Roadmap

Client: Carollette Phillips (LaShelle's School of Dance)
Status: Attendance + basic payments shipped. Client wants billing, parent access, waivers.

---

## Phase 1: Billing & Balance Ledger
> "Can it show charges/balances like a spreadsheet format that keeps a tally?"

She needs to see what each family OWES vs what they've PAID — not just payment records.

- [ ] **1a.** Add transaction `type` field: `charge` vs `payment`
  - Charges = tuition due, costume fee, shoe fee, recital fee, etc.
  - Payments = what they actually paid (cash, zelle, venmo, etc.)
- [ ] **1b.** Student ledger page (`/students/<id>/ledger`)
  - Spreadsheet-style table: Date | Description | Charge | Payment | Balance
  - Running balance column (charges add, payments subtract)
  - Summary at top: Total Charges, Total Paid, Balance Due
- [ ] **1c.** Update Payments page with balance overview
  - Show each student's current balance (what they owe)
  - Color code: green = paid up, red = balance due
  - Quick "Add Charge" and "Add Payment" buttons
- [ ] **1d.** Bulk charge tool
  - "Charge all students in [class] $X for [tuition/costumes/etc.]"
  - So she doesn't have to add tuition one student at a time

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

## Phase 3: Waiver Signing
> "Waiver signing?"

Digital waiver that parents sign — liability release, photo consent, medical authorization.

- [ ] **3a.** Waiver template model — admin creates waiver text
- [ ] **3b.** Signing flow — parent views waiver, types name, checks box, timestamp recorded
- [ ] **3c.** Waiver status on student profile — signed / not signed / expired
- [ ] **3d.** Admin view — who hasn't signed yet, send reminders

---

## Priority Order

**Phase 1 first.** She's already in the payments page and this is the immediate ask.
Phase 2 next — unlocks parent self-service.
Phase 3 last — nice to have, less urgent.

## Out of Scope (for now)
- Actual payment processing (Stripe, Square) — she's using Cash App/Zelle/Venmo directly
- Automated recurring billing — manual charge entry for now
- Email/SMS notifications — future
