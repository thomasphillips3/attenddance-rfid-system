# AttenDANCE — Production-Readiness Assessment

**Audited:** 2026-07-05 · **Context:** Studio year over, recital done, summer session started, Jackrabbit canceled. This system is the fall plan of record. Client: LaShelle's School of Dance (LSO Dance).
**Method:** Static review of ~6.8k LOC (models, API, main, helpers, config, migrations, templates) + a live runtime harness (`tests/smoke_audit.py`) that boots the app, seeds two unrelated families, and probes access control + smoke-tests every no-arg route.

---

## Verdict

**Not production-ready as-is — but close, and the blockers are concentrated.** The feature breadth is genuinely impressive and the UI redesign is fully landed (0 legacy-style files remain). What stands between here and go-live is **two P0 security holes that are individually catastrophic for a system holding minors' PII and money**, one P1 billing defect, and a short list of parity/polish gaps. The P0s are both fixable in an afternoon; neither requires new features.

The single most important sentence in this doc: **right now, any parent who logs in can read every other family's child records (allergies, medical needs, emergency contacts) and the studio's entire financial ledger, and anyone who has seen the GitHub repo can forge an admin login.** Fix those two before a single real family gets an account.

Severity counts: **2 P0, 3 P1, 5 P2, 3 P3** (this pass; billing/bug/parity depth still expanding in later iterations).

---

## P0 — Blockers (must fix before any real user gets an account)

### [P0-1] Production SECRET_KEY is a committed, known placeholder → full auth bypass + secret decryption
- **Where:** `fly.toml:9` — `SECRET_KEY = 'fly-demo-key-change-for-real-prod'`, plus the fallback `'dev-secret-key-change-in-production-12345'` in `config/config.py:15`.
- **Why it's catastrophic:** Flask signs session cookies with `SECRET_KEY`. It's set as a **plaintext `[env]` value in a committed file** (not a Fly *secret*), so its value is in git history on a named GitHub repo. Anyone with the value can mint a cookie for `is_admin=True` and log in as admin — no password needed. Worse, `app/crypto.py` derives its Fernet key from `SECRET_KEY`, so the "encrypted at rest" Square access token is decryptable by anyone with the repo. The encryption is theater.
- **Fix (this iteration):** Remove the key from `fly.toml`; make `ProductionConfig` refuse to boot if `SECRET_KEY` is unset or matches a known weak/default value (fail closed). Then Thomas runs `fly secrets set SECRET_KEY=$(python3 -c 'import secrets;print(secrets.token_hex(32))')`. Safe to rotate now — Square isn't configured yet, so no encrypted secret gets orphaned.

### [P0-2] Broken access control (IDOR) on the core student/family/transaction API
- **Where:** `app/api/routes.py` — `GET/PUT/DELETE /api/students/<id>` (144–209), `GET /api/students/<id>/ledger` (695), `GET /api/families/<id>/ledger` (1214), `GET /api/students` (roster), `GET /api/transactions` (all money). All carry only `@login_required`; no staff or ownership check.
- **Proven live** (`tests/smoke_audit.py`, parent A vs parent B's child):
  - `GET /api/students/2` → **200** (reads another child's allergies/special-needs/emergency contact)
  - `DELETE /api/students/2` → **200** (deactivates another family's child)
  - `GET /api/students/2/ledger`, `GET /api/families/2/ledger` → **200** (another family's finances)
  - `GET /api/students`, `GET /api/transactions` → **200** (whole-studio roster + all transactions)
- **Note:** Newer endpoints (skills/waivers/payment-plan) *do* gate with `_parent_student_ids()` and return 403 — the pattern exists; the original CRUD predates it. This is a consistency fix, not new design.
- **Fix (this iteration):** Add `_staff_only()` + `_require_student_access()` / `_require_family_access()` helpers and apply to every legacy endpoint. Mutations (create/update/delete/assign-rfid) → staff only. Reads of a specific student/family → staff or linked parent. List endpoints → staff only.

---

## P1 — Serious (fix before relying on the feature)

### [P1-1] Square invoice OVERCHARGES families who have paid down their balance ✅ FIXED
- **Where:** `app/api/routes.py` (`send_student_invoice`). Line items were built from **all charges ever** (ignoring payments). Critically, `square_service.send_invoice`'s own docstring says *"amount_cents … unused directly — line items drive it"* — so Square's order total is the **sum of line items = gross charges**, and the `amount_cents` (balance) was ignored entirely. A student with $200 charged / $150 paid was invoiced **$200**, not $50. Confirmed overcharge, not just a display bug.
- **Fix applied:** line items now carry a single "Outstanding balance" line equal to the net balance, so the Square total == the amount owed. Endpoint also gated staff-only.

### [P1-2] No autopay / cards-on-file — the core Jackrabbit billing feature is absent (parity)
- **Evidence:** grep for autopay/card-on-file/subscription → **0 hits**. Recurring billing only creates *charge* ledger rows; actual collection is manual reconciliation ("I paid via Zelle/CashApp") or a one-off Square invoice a parent must click. Jackrabbit's headline is auto-charging saved cards on a schedule.
- **Operational impact:** The studio *can* run fall on manual reconciliation (many small studios do), so this is not a hard blocker — but chasing unpaid tuition by hand is the biggest day-to-day tax vs Jackrabbit. Rank as the top post-launch build.

### [P1-3] CSRF protection is disabled app-wide
- **Where:** No `CSRFProtect` anywhere; `WTF_CSRF_ENABLED=False` only in test config; the app is session-cookie auth with many `fetch()` POSTs and HTML forms. Sole mitigation is `SESSION_COOKIE_SAMESITE='Lax'`, which blocks most cross-site POSTs but is not defense-in-depth and doesn't cover same-site injection or older browsers.
- **Fix:** Add Flask-WTF `CSRFProtect`, emit a token in `base.html`, and send `X-CSRFToken` from the `fetch()` wrapper. Medium effort (touches every POST) — schedule deliberately, not a hot-fix.

---

## P2 — Should fix

- **[P2-1] Recurring charges silently skip short months — ✅ FIXED.** `_process_recurring_charges` skipped a charge when `today.day < day_of_month`, so a charge set for the 29th–31st never fired in Feb (and 31 never fired in any 30-day month) → missed tuition 1–5 months/yr with no error. Now clamps the due day to the month's last day (`min(day_of_month, monthrange)`), so it fires on the last day of short months. Math verified (Feb + day-31 → fires day 28). A date-frozen regression test needs `freezegun` (not yet a dep — see P3-3).
- **[P2-2] 126 raw `prompt()/alert()/confirm()` calls** across ~20 templates for data entry and errors. `confirm()` on deletes is tolerable; `prompt()` for data entry (recital new-year, late fees, payment-plan create, donate, makeup-request) is unprofessional for a paying client. Replace the `prompt()` flows with real modals.
- **[P2-3] Four parallel toast/flash systems** (base flash, parent `toast()`, recital `msg()`, pending `showMsg()`). Unify into one helper for consistent feedback.
- **[P2-4] Zero `aria-label`s app-wide** — every icon-only button (hamburger, close X, chevrons, search, logout) is unnamed for screen readers. Add labels; it's cheap.
- **[P2-5] Verify the `/api/cron/run` token compare is constant-time and rejects empty tokens** (`routes.py:3099`) — confirm an unset `cron_token` can't be bypassed with an empty string. (Needs a focused read next iteration.)

## P3 — Polish

- **[P3-1] 2 of 11 `<img>` tags lack `alt`.**
- **[P3-2] `SECRET_KEY`/`JWT_SECRET_KEY` still have insecure dev fallbacks** in base `Config` — fine for dev, but the prod guard (P0-1) is what makes them safe.
- **[P3-3] No automated test suite in-repo** (prior smoke harness wasn't kept). `tests/smoke_audit.py` added this pass is the seed of one; grow it into CI.

---

## What's genuinely solid (don't re-litigate)

- **UI redesign is fully landed** — 0 files hit the legacy-style grep (`gray-*`, `indigo-`, old hex, `bg-white shadow`). The purple/gold token system is applied consistently.
- **80/80 no-arg admin GET routes return < 500** in the smoke run — no broken staff pages at that level.
- **Newer endpoints already enforce ownership** (`_parent_student_ids`), so the team knows the pattern.
- **App boots clean**, 238 routes, single-worker memory posture is deliberate and documented.

---

## Fix log (updated each iteration)

### Iteration 1 — DONE (verified by `tests/smoke_audit.py`, 24/24 pass)
- **P0-2 broken access control — FIXED & VERIFIED.** Added `_staff_only` / `_require_student_access` / `_require_family_access` helpers and a fail-closed `@bp.before_request` that default-denies parents on every mutating method except a 7-endpoint allowlist. Applied ownership/staff guards to the leaking CRUD, ledgers, balances, roster, transactions, families, messages, attendance, dashboard-stats, rfid, recurring-charges, class-enrollments, rules-status, and rule-acknowledge. Harness proves: parent can no longer read other families' data, pull the roster, fabricate a payment, or fire an email blast — and parent-allowed writes (claim/donate) still work.
- **P0-1 committed prod SECRET_KEY — FIXED.** Removed the key from `fly.toml`; production now **refuses to boot** on a missing/known-default key (`app/__init__.py`). Verified: refuses weak/absent, boots on a strong key, dev unaffected.
  - ⚠️ **REQUIRED before next deploy (Thomas):** `fly secrets set SECRET_KEY=$(python3 -c 'import secrets;print(secrets.token_hex(32))')` — otherwise prod won't start (by design). Safe to rotate now: Square isn't configured, so no encrypted secret is orphaned.
- **P1-1 Square overcharge — FIXED.** Invoice line items now sum to the net balance.
- Added `tests/smoke_audit.py` (boot + IDOR + write-guard + no-arg smoke) as the regression seed.

### Iteration 2 — DONE (verified by `tests/test_billing.py`, 11/11 pass)
- **Late-fee double-application — FIXED.** `apply_late_fees` had no idempotency guard; an admin double-click / refresh-repost applied a *second* late fee to every over-threshold family. Now skips any student already charged a late fee this calendar month (matches the recurring-charge guard). Verified: second run charges 0, each student ends with exactly one fee.
- **Billing correctness verified (no change needed):** `allocate_family_payment` loses/invents no pennies across exact/partial/overpayment/odd-cent inputs and caps each child at their balance (money is `Numeric(10,2)` at rest; the `float()` casts in helpers are a smell but safe given 2-decimal values). `confirm_pending_payment` blocks re-confirm (`status != 'pending'`). Square webhook is idempotent (`if rec.paid_at`) and HMAC-verified when keyed.
- **New P2 logged:** Square webhook records the *full* invoice amount on a `PARTIALLY_PAID` event and then sets `paid_at`, so the later `PAID` event is ignored — over-counts the payment and drops the remainder. Needs a product call on partial-payment semantics; Square isn't active yet so it's not urgent.

### Remaining for next iterations
- P1-2 autopay/cards-on-file (biggest parity build — needs Thomas's go-ahead, it's a feature), P1-3 CSRF (medium refactor, touches every POST), P2-2 prompt() flows, P2-3 toast unify, P2-4 aria-labels, P2-5 cron token constant-time check, P2 Square PARTIALLY_PAID semantics, P3s. Full Jackrabbit parity matrix still to expand.
