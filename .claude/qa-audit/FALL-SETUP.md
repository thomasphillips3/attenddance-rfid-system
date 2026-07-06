# Fall Season Setup — Operator Runbook

How to stand up the fall session in AttenDANCE, in order. Written for
Carollette (setup) with the decision points flagged for Wilkanda. Everything
here exists and is tested — this is just the order of operations.

Assumes the app is deployed and the admin password is changed
(see [GO-LIVE.md](GO-LIVE.md)).

---

## 1. Close out summer (5 min)

- **Classes page → Cancel Class** on each summer-only class. Cancelling
  automatically stops that class's recurring tuition charges, removes it from
  every dancer's schedule, and clears its waitlist. Past attendance and
  charges stay on the books.
- Don't touch classes that continue into fall.
- Any family that still owes shows on the **Aging (A/R)** report — withdrawn
  or not, a balance stays visible until it's paid.

## 2. Build the fall schedule (30–60 min)

- **Classes page → Add Class** for each fall class: name, day, time,
  instructor, and **max students** (the cap is enforced — enrollment and
  registration approvals respect it).
- **Payments page → recurring charges**: one per class — amount, category
  `tuition`, and the day of the month it bills. Note: the app sleeps when
  idle, so a charge posts when the app first wakes on or after that day; the
  engine never double-charges and catches up on short months automatically.
- Optional, in **Settings**: late fee amount + minimum balance (applied via
  the Payments page when you choose, never automatically), Zelle/Cash App
  display, message templates.

## 3. Open enrollment (5 min)

- **Enrollment page → toggle "Registration open"**, then share the
  registration link (`/register`) — text it, put it on the flyer, whatever.
- Returning families use the SAME link. The system recognizes them by the
  parent email: no duplicate family gets created, a dancer who already exists
  is re-enrolled in the classes they picked (and reactivated if they were
  withdrawn last year), and new siblings are added. The approval message
  spells out exactly what happened.

## 4. Approve registrations (ongoing)

- **Enrollment page** shows pending registrations with a badge in the nav.
- **Approve** creates/updates the family, dancers, and class enrollments,
  respecting class caps — if a class is full, the approval says who was
  skipped so you can raise the cap or waitlist them (class page → Manage
  Students → Add to Waitlist).
- **Portal access:** open the dancer's page (Students → dancer → detail).
  The **Portal Access** card shows linked parent accounts, generates invite
  codes for new parents, and makes **password-reset links** for locked-out
  ones (text the link; it expires in an hour).

## 5. First week of classes

- **Check-in = the Take Attendance page** on a tablet or laptop. Teachers
  have access. (The RFID card reader does NOT work with the hosted system —
  don't plug in the old Pi setup; it would write to a separate database.
  Card-tap can be built if wanted — see the assessment, decision 4b.)
- Teachers can also message their class from the Messages page (email goes
  out automatically once SMTP is configured; until then the system hands you
  the address list to copy).

## 6. First billing cycle

- Recurring tuition posts automatically on each class's billing day.
- **Mid-month joiners are NOT auto-charged for their first month** — post
  their first charge manually from the Payments page (or tell Thomas to build
  proration, decision 3c).
- Parents pay by Zelle/Cash App and report it on their portal → shows in the
  **Pending** inbox → confirm it (this posts the payment, splits family
  payments across siblings, and emails a receipt once SMTP is on).
- Chase balances with the **Aging (A/R)** report + the reminder button.

## Weekly rhythm once running

| When | What |
|------|------|
| Daily-ish | Pending payments inbox; new registrations |
| Weekly | Aging report; send reminders if needed |
| Monthly | Revenue report; download a backup (Settings → Data & Backup) |

## If something looks wrong

Don't edit around it — text Thomas. The audit log (bottom of the Pending
payments page) records every money action, so nothing is lost.
