# PR title + description (ready to paste)

Copy below when opening the merge PR for `fix/api-authorization-and-secret-key`.

---

**Title:**

Production hardening for the fall launch: authorization, billing correctness, and the enrollment flow

**Body:**

This branch started as a fix for two critical findings — any logged-in parent
could read every family's child records and finances (broken access control),
and the production SECRET_KEY was a committed placeholder (admin-session
forgery + decryption of at-rest secrets). It grew into the full
production-readiness pass for the fall season, since this system replaces
Jackrabbit as the plan of record.

What's in it, by area:

- **Authorization:** default-deny model over the whole API. Parents can only
  reach their own children; teachers are locked to least privilege (attendance,
  rosters, instructional tools — no billing, no roster mutations); all money
  surfaces are admin-only. The demo parent account is disabled at production
  boot.
- **Billing correctness:** Square invoices bill the net balance (was gross
  charges), recurring charges are idempotent, handle short months, never bill
  the setup month retroactively, and stop when a dancer withdraws. Every
  check-then-act money path (payment confirm, webhook, late fees, costume
  charges, registration approve) is concurrency-safe.
- **Fall enrollment:** the public registration flow recognizes returning
  families (matched by family or student email against the real data shape),
  re-enrolls returning dancers instead of duplicating them, reactivates
  withdrawn dancers, adopts pilot-era orphan records into families, links new
  siblings to the family's portal account, flags returning families in the
  admin queue, and carries volume circuit breakers.
- **Operational safety:** Eastern-time correctness on every event timestamp,
  fail-closed SECRET_KEY boot guard, ProxyFix so texted reset links are https,
  timeouts on every outbound call (SMTP/Twilio/Square), JSON errors on API
  routes, no PII in retained logs, admin-generated password-reset links for
  parents (the no-SMTP recovery path), and a consistent-snapshot database
  backup.

Verification: 458 automated checks run in CI on this PR (access-control sweeps
for all three roles, malformed-input fuzzing over every write endpoint, money
math, the full enrollment arc, and a prod-config boot). The suite was
mutation-tested — five representative regressions re-introduced one at a time
all turned it red. Deploy was rehearsed three ways: the production Docker
image built and boot-tested locally, a request battery against it in the
proxied production shape, and the branch booted against a copy of the real
production database (migrations, self-cleans, and every key page green on
real data).

After merge: deploy, then change the seeded admin password immediately —
`.claude/qa-audit/GO-LIVE.md` is the ordered runbook, and
`.claude/qa-audit/FALL-SETUP.md` is the operator guide for standing up the
season.
