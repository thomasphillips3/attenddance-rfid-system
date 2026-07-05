# AttenDANCE — Production-Readiness Assessment

**Audited:** 2026-07-05 · **Context:** Studio year over, recital done, summer session started, Jackrabbit canceled. This system is the fall plan of record. Client: LaShelle's School of Dance (LSO Dance).
**Method:** Static review of ~6.8k LOC (models, API, main, helpers, config, migrations, templates) + a live runtime harness (`tests/smoke_audit.py`) that boots the app, seeds two unrelated families, and probes access control + smoke-tests every no-arg route.

---

> **To actually launch:** follow [GO-LIVE.md](GO-LIVE.md) — the ordered runbook (required secrets → deploy → smoke test → optional client-side config).

## Verdict

**Not production-ready as-is — but close, and the blockers are concentrated.** The feature breadth is genuinely impressive and the UI redesign is fully landed (0 legacy-style files remain). What stands between here and go-live is **two P0 security holes that are individually catastrophic for a system holding minors' PII and money**, one P1 billing defect, and a short list of parity/polish gaps. The P0s are both fixable in an afternoon; neither requires new features.

**UPDATE (after 5 fix iterations):** both P0s and the serious P1s are now **fixed and verified** by two runtime harnesses (`tests/smoke_audit.py` 32/32, `tests/test_billing.py` 16/16) on branch `fix/api-authorization-and-secret-key`, plus an A/R aging report was built and the parent portal's fatal JS bug (P1-4 — the whole portal's JavaScript was dead) was found and fixed by running it in a real browser. The app is **safe to onboard real families onto once `SECRET_KEY` is set as a Fly secret and the seeded admin password is changed**. What remains is one feature decision (auto-pay) and staff-side UX polish — not data-safety or money-correctness blockers.

Original headline (now resolved): any logged-in parent could read every other family's child records and the studio's entire ledger, and anyone with the repo could forge an admin login.

Severity counts (original pass): **2 P0, 3 P1, 5 P2, 3 P3.** Now resolved: 2 P0, 2 P1, 4 P2/P3. Remaining: P1-2 auto-pay (feature), plus UX-polish P2/P3s and parity enhancements (AR aging, per-page a11y).

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

### [P1-4] The ENTIRE parent portal's JavaScript was broken by an escaping bug — ✅ FIXED
- **Where:** `parent/dashboard.html` — a Zelle help string was written `...bank\\'s Zelle...` (double backslash). In a single-quoted JS string `\\` is a literal backslash, so the `'` **closed the string early**, producing a `SyntaxError` that killed the whole `{% block extra_js %}` script.
- **Impact (severe):** *nothing* dynamic on the parent dashboard ran — no payment methods, no "I paid" reporting, no makeup requests, no company/recital/costume/ticket sections, no forms badges. Parents saw a static shell. Confirmed live: before the fix, **zero** `/api/*` calls reached the server on `/parent`; after, all 8 `init()` fetches fire.
- **Why the earlier harness missed it:** the template verification harness Jinja-compiles and renders templates — it can't catch a *JavaScript runtime* syntax error. Only running the page in a real browser surfaced it. (Lesson logged: the smoke harness should node-check rendered inline scripts.)
- **Fix:** `\\'` → `\'`. Verified: `node --check` clean, and both rebuilt modals POST successfully end-to-end.

### [P1-1] Square invoice OVERCHARGES families who have paid down their balance ✅ FIXED
- **Where:** `app/api/routes.py` (`send_student_invoice`). Line items were built from **all charges ever** (ignoring payments). Critically, `square_service.send_invoice`'s own docstring says *"amount_cents … unused directly — line items drive it"* — so Square's order total is the **sum of line items = gross charges**, and the `amount_cents` (balance) was ignored entirely. A student with $200 charged / $150 paid was invoiced **$200**, not $50. Confirmed overcharge, not just a display bug.
- **Fix applied:** line items now carry a single "Outstanding balance" line equal to the net balance, so the Square total == the amount owed. Endpoint also gated staff-only.

### [P1-2] No autopay / cards-on-file — the core Jackrabbit billing feature is absent (parity)
- **Evidence:** grep for autopay/card-on-file/subscription → **0 hits**. Recurring billing only creates *charge* ledger rows; actual collection is manual reconciliation ("I paid via Zelle/CashApp") or a one-off Square invoice a parent must click. Jackrabbit's headline is auto-charging saved cards on a schedule.
- **Operational impact:** The studio *can* run fall on manual reconciliation (many small studios do), so this is not a hard blocker — but chasing unpaid tuition by hand is the biggest day-to-day tax vs Jackrabbit. Rank as the top post-launch build.

### [P1-3] CSRF protection was disabled app-wide — ✅ FIXED (Origin check)
- **Was:** No `CSRFProtect`; 157 raw `fetch()` POSTs + HTML forms with only `SameSite=Lax` as mitigation.
- **Fix applied:** an app-wide `before_request` (`_csrf_origin_guard`) rejects any POST/PUT/DELETE/PATCH whose `Origin` (or `Referer`) host differs from the request host — the pattern many JSON APIs use. Browsers always send `Origin` on cross-site state-changing requests, so this blocks classic CSRF with **zero changes to the 157 fetch calls** and no new dependency; the HMAC-verified webhook and token-verified cron endpoint are exempt. Verified: cross-origin write → 403, same-origin/no-Origin → pass. Combined with `SameSite=Lax` this is a solid production posture. (Token-based Flask-WTF remains an option for belt-and-suspenders, but would require patching all 157 fetches.)

---

## P2 — Should fix

- **[P2-1] Recurring charges silently skip short months — ✅ FIXED.** `_process_recurring_charges` skipped a charge when `today.day < day_of_month`, so a charge set for the 29th–31st never fired in Feb (and 31 never fired in any 30-day month) → missed tuition 1–5 months/yr with no error. Now clamps the due day to the month's last day (`min(day_of_month, monthrange)`), so it fires on the last day of short months. Math verified (Feb + day-31 → fires day 28). A date-frozen regression test needs `freezegun` (not yet a dep — see P3-3).
- **[P2-2] Raw `prompt()` data-entry flows → modals — parent + leads + company + pending-payments DONE; ~30 remain.** Converted to real modals and verified live: parent-facing (donate, makeup), leads add, all three Performance Company flows, and the **whole pending-payments page** (apply-late-fees, new-payment-plan, reject-payment) — the payment-plan flow was 5 chained prompts including a *type-a-number* student picker, now a dropdown showing balances. Pending-payments is a fall-critical page, so clearing it fully matters. Remaining `prompt()` calls are in recital (off-season), donations-admin, waivers, skills, makeups — lower priority. `confirm()` guards on deletes are fine to keep.
- **[P2-3] Four parallel toast/flash systems** (base flash, parent `toast()`, recital `msg()`, pending `showMsg()`). Unify into one helper for consistent feedback.
- **[P2-4] `aria-label`s — ✅ DONE app-wide.** Base shell (done earlier) plus a sweep of every icon-only button across the templates (delete/edit/close/remove/move/copy — ~23 buttons in 12 files) now have accessible names + `aria-hidden` on the decorative icons. 0 unlabeled icon-only buttons remain. (Caught and fixed 2 buttons a batch script mislabeled — the Donate and Save buttons had visible text and briefly got a wrong "Close" label; both corrected.)
- **[P2-5] `/api/cron/run` token compare — ✅ FIXED.** The `not token` guard already rejected an unset token (no empty-string bypass), but the comparison used `!=`. Switched to `secrets.compare_digest` (constant-time) to avoid leaking the token via response timing. Verified: no/wrong token → 403, correct → 200.

- **[P2-6] Login page displayed working admin credentials — ✅ FIXED.** `auth/login.html` showed a "Demo Credentials: admin / admin123" block with one-click "Use" buttons — handed anyone the default admin login. Now gated behind `{% if config.DEBUG %}` (shown in dev, hidden in production). Verified: dev renders it, `DEBUG=False` doesn't. **Still recommended:** change the seeded admin password from `admin123` for production.

- **[P2-7] Financial writes accepted unchecked amounts — ✅ FIXED.** `create_transaction` and `bulk_charge` (staff-only) passed `data['amount']` straight to the DB with no validation, so a typo could post a **negative** charge/payment (which silently corrupts a balance — a −$50 charge reads as a credit) or a non-numeric value (→ 500), and `bulk_charge` applied it to *every* enrolled student; `type` wasn't constrained to charge/payment, and a bad `transaction_date` 500'd. Now both use shared `_valid_amount` (numeric, >0, sane ceiling) + `_parse_txn_date` + a type whitelist. Verified (negative/non-numeric/absurd/bad-type all 400; valid charge 201). The untrusted parent paths (`claim_payment`, `create_donation`) were already validated.

## P3 — Polish

- **[P3-1] 2 `<img>` tags lacked `alt` — ✅ FIXED** (Zelle QR preview + recital ad; 0 remain).
- **[P3-2] `SECRET_KEY`/`JWT_SECRET_KEY` still have insecure dev fallbacks** in base `Config` — fine for dev, but the prod guard (P0-1) is what makes them safe.
- **[P3-3] Automated tests — ✅ IN CI.** `tests/smoke_audit.py` (57) + `tests/test_billing.py` (16) now run on every push/PR via `.github/workflows/tests.yml`, using the same `requirements-deploy.txt` set prod runs. Verified in a clean CI-mirror venv (57/57 + 16/16). The safety net is now durable — future changes can't silently regress access control, billing math, or the fall-critical flows.
- **[P3-4] CDN scripts load without Subresource Integrity.** `base.html` + report pages pull Tailwind, Alpine, Chart.js, FontAwesome from CDNs without `integrity`/`crossorigin` — a CDN compromise could inject script. Low likelihood (reputable CDNs) but cheap to harden: pin versions + add SRI hashes app-wide (do it consistently, not per-tag).

---

## Waiver signing (enrollment flow) — verified end-to-end

New families sign waivers at enrollment, so the positive path was verified (not just the IDOR block):
- A parent signs their **own** child's waiver (`POST .../waivers/<tid>/sign` → 200) and it reads back as `signed: true`.
- A typed signature is required (empty → 400); an idempotent re-sign updates the existing signature.
- **Decline rules hold:** declining a mandatory form → 400 ("requires agreement"); declining an opt-out form (e.g. photo release, `allow_decline`) → 200. Still blocks signing another family's child (403). Regression-guarded.

## Taking attendance (most-used fall feature) — verified live

The single most-used daily flow was exercised end-to-end and works:
- The card-based take-attendance UI (`/take-attendance/<class_id>`) renders per-student week grids with the current week highlighted.
- Marking present persists (`POST /api/attendance/toggle` → 201, `present: true`); tapping again removes it (→ 200, `present: false`) — correct idempotent toggle.
- Parents can't mark attendance (write-guard, 403). Regression-guarded in the harness.

## Email/SMS message blasts (studio→families comms) — audited & verified

The fall communication path was reviewed and comes back **sound**:
- Recipient resolution for `all` / `class` / `individual` is correct and de-duplicated (a `set`), uses a join to avoid N+1, and prefers parent email over student email.
- **Graceful degradation:** when SMTP isn't configured (current prod state), the blast is *saved* and the resolved emails are returned for manual copy; an SMTP send failure saves the message and returns the recipients too — nothing is silently lost.
- Parents can't send (write-guard, 403). Hardened this pass: a non-numeric `recipient_filter` now returns 400 instead of 500.
- Verified in the harness (blast to `all` resolves 2 recipients + degrades gracefully; missing subject → 400; bad class filter → 400; parent → 403).

## Public self-registration (fall-enrollment path) — audited & verified

The most-load-bearing untrusted flow for fall was reviewed end-to-end and comes back **sound**:
- **Submit** (`POST /api/register`, public): gated by `registration_open`, requires parent name/email + ≥1 dancer, stores the payload as JSON. Hardened this pass: added email-format validation.
- **No stored XSS:** the admin `/registrations` page escapes *every* attacker-controlled field (`parent_name`, email, phone, note, student names/allergies) via `esc()`.
- **Approve** (`admin`): creates Family + Students + enrollments using only whitelisted fields (**no mass assignment** — a crafted `is_admin`/etc. is ignored), idempotent (`status != 'pending'` guard). Hardened this pass: enrollments now filter to **existing** class IDs so a class deleted between submit and approval can't create a dangling enrollment that 500s the roster later.
- **Verified end-to-end** in the harness (closed→403, bad email→400, no dancers→400, valid→201, queued, approve creates 1 family + 2 students, re-approve→400) and in the browser (both the closed-state page and the live enrollment form render on-brand).

## Functional / reliability sweep — comes back clean

**Client-side runtime layer — fully swept (iteration 6), clean after the P1-4 fix:**
- **All rendered inline JS node-checked:** 84 pages, 56 inline scripts parsed via `node --check` (as admin) — 0 syntax errors. The parent dashboard (P1-4) was the only broken page; every staff page is clean.
- **All fetch endpoints exist:** 147 `fetch('/api/...')` calls across the templates cross-checked against the registered route map — 0 dead endpoints (the only "unmatched" were string-concatenation prefixes whose real routes exist).
- **Browser runtime sweep:** loaded 13 JS-heavy staff pages (transactions, pending, recital-hub, company, analytics, calendar, waivers, skills, leads, makeups, timeclock, settings, dashboard) + the parent portal in a real browser — **zero console errors, zero failed API requests**.

**Deletion / cascade integrity — audited (all 30 DELETE endpoints), sound:**
- SQLite FK enforcement is off (no `PRAGMA foreign_keys=ON`), so orphaned rows are *possible* in principle — but the app avoids them by design: **containers soft-delete** (student, location, performance group, costume, skill → `is_active=False`), and **family/class have no delete endpoint at all**, so students/enrollments can't be orphaned by removing a parent.
- The one hard-delete with dependents (`delete_ticket_type`) explicitly removes its `TicketOrder`s first — verified empirically (deleting a type with a live order leaves 0 orphaned orders).
- Net: no cascade/orphan bug. (Flipping on FK enforcement is *not* recommended without adding `ON DELETE` rules first — the current manual-cleanup pattern assumes it's off, so enabling it would make existing hard-deletes error.)

Server-side areas most likely to hide bugs; no new P0/P1 beyond what's already fixed:
- **Migrations are idempotent** (`app/migrations.py`): every `ALTER TABLE` is guarded by a column-existence check and is additive-only; `db.create_all()` handles new tables before migrations run. Fresh DB and existing prod DB both boot.
- **Silent failures:** the `except Exception:` blocks log via `logger.exception`; the one `except: pass` (`email.py`) is on `smtp.quit()` in a `finally` — harmless, real send errors propagate.
- **No meaningful N+1 / memory risk at this scale:** singular `calc_balance` calls are all single-student contexts (invoice, reminder, one parent's few children); bulk paths use `calc_balance_bulk` (one aggregate query); unbounded `.all()` only hits the students table (hundreds of rows) — fine on the 256MB box. The 1-worker gthread posture is deliberate and documented.
- **Startup side effects** (recurring charges, reminders) are wrapped/guarded; recurring is now short-month-safe.

## Jackrabbit parity — capability matrix

Verdict: **strong parity for daily operations; the one structural gap is automated payment collection.** A studio can run the fall session on this today (registration, scheduling, attendance, tuition charges, parent portal, recital, comms all work), but tuition *collection* is manual — the biggest ongoing difference from Jackrabbit.

| Capability | Status | Notes |
|---|---|---|
| Online registration & enrollment | **PRESENT** | Public `/register` → Registration → admin approve; class waitlists |
| Family & student management | **PRESENT** | Family/siblings, full student records + measurements |
| Class scheduling (day/time/level/age) | **PRESENT** | `DanceClass` + visual `/calendar` |
| Attendance & absences | **PRESENT** | Attendance + RFID + makeups |
| Tuition charges & recurring billing | **PRESENT** | Recurring charge rows, per-category balances, bulk charge |
| **Auto-pay / cards on file** | **MISSING** | No saved-card auto-charge — the #1 gap (P1-2) |
| Online card payment | **PARTIAL** | One-off Square invoices (manual send); no integrated checkout/autopay |
| Payment reconciliation | **PRESENT** | Parent "I paid" → admin confirm inbox; family-split allocation |
| Parent portal | **PRESENT** | View account/schedule, report payments, waivers, tickets, makeups, donate |
| Skills / levels | **PRESENT** | Skill/StudentSkill + printable certificates |
| Costume & recital management | **PRESENT** | Recital Hub: numbers/cast/costumes/tickets/awards/ads/booklet |
| Email / SMS communication | **PRESENT*** | Blasts + Twilio SMS — *needs SMTP/Twilio creds entered to actually send |
| Late / returned-payment fees | **PARTIAL** | Late fees ✅ (now idempotent); no NSF/returned-payment or refund/void path |
| Financial statements | **PRESENT** | Year-end student/family + 501(c)(3) giving statements |
| Waivers & policies | **PRESENT** | Digital waivers + per-rule acknowledgment |
| Staff/teacher roles | **PARTIAL** | admin vs teacher tiers exist, but coarse — a teacher sees all students, not just their classes |
| Management reporting (revenue/enrollment/AR aging/export) | **PRESENT** (was PARTIAL) | ✅ Revenue report (`/reports/revenue`: billed-vs-collected by month + by category + totals) · ✅ AR aging (`/reports/aging`) · ✅ CSV export (roster + transactions) · retention/enrollment analytics · ticket revenue. Remaining nice-to-have: enrollment/capacity summary + CSV of the aging report |

**Top parity risks for fall, ranked:** (1) auto-pay/cards-on-file — manual collection is the daily tax; (2) AR aging report — the owner will want a "who owes, how overdue" view to chase tuition; (3) confirm SMTP/Twilio are configured so receipts/reminders actually send (currently save-only).

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

### Iteration 3 — DONE
- **Functional/reliability sweep** (migrations idempotency, silent failures, N+1/memory) — clean, no new bugs (see section above).
- **Jackrabbit parity matrix** produced (see section above) — verdict: strong daily-ops parity, auto-pay is the one structural gap.
- **Accessibility:** base-shell icon buttons + search input labelled (`aria-label`/`aria-hidden`); both missing `<img alt>` fixed. All 46 templates still Jinja-compile.

### Iteration 4 — DONE (verified live in preview + `tests/test_billing.py` 16/16)
- **A/R aging report built** (`GET /api/reports/aging` staff-only + `/reports/aging` admin page + nav link): FIFO payment application, 0-30/31-60/61-90/90+ buckets, per-student rows + totals, empty state, overdue buckets flagged red. Closes parity gap #2. FIFO math unit-tested (boundaries, partial payment, overpayment credit) and verified end-to-end in the live preview ($120@95d + $80@40d + $60@5d − $100 payment → 90+=$20, 31-60=$80, current=$60, total=$160).
- **Found + fixed via preview:** login page exposed demo `admin/admin123` — now gated behind `config.DEBUG` (P2-6), hidden in production.
- `run.py` now honors `PORT` (12-factor) so it runs under any harness/PaaS.

### Iteration 5 — DONE (verified live in browser; smoke 32/32, billing 16/16)
- **P1-4 — found & fixed the parent portal's fatal JS escaping bug** (see P1-4). The whole parent dashboard was non-functional; now all sections load. **This was the most impactful find of the audit** and only surfaced by running the page in a real browser.
- **Parent-facing `prompt()` flows → real modals** (donate + makeup request), verified end-to-end (both POST 201 in the live preview) with on-brand styling and accessible close buttons.
- **Added a rendered-inline-JS `node --check` guard to the smoke harness** so a JS syntax error in any JS-heavy page fails CI instead of silently bricking a page.

### Iteration 6 — DONE (whole-app runtime verification)
- **Swept the entire client-side runtime** (see the Functional section): node-checked every rendered inline script (56 across 84 pages), cross-checked all 147 `fetch()` calls against the route map (0 dead endpoints), and browser-loaded 13 JS-heavy staff pages — **all clean, zero console errors, zero failed requests**. Confirms P1-4 was the only runtime break; the app's JS layer is now sound end-to-end.

### Iteration 7 — DONE (verified live; smoke 37/37)
- **CSV export built** (`/api/reports/students.csv` + `/api/reports/transactions.csv`, staff-only): roster export (contacts, DOB, emergency, allergies, balance) and transaction ledger export (optional `?start=&end=` range) with proper attachment headers. "Export CSV" buttons on the Students and Payments pages; an "Aging" shortcut added to Payments too. Closes the "get my data out" reporting gap Jackrabbit covers. Verified live — real roster CSV downloads with correct data; parents blocked (403).

### Iteration 8 — DONE (verified live; smoke 39/39)
- **Revenue report built** (`GET /api/reports/revenue` staff-only + `/reports/revenue` admin page + nav link): headline totals (collected this month/year/all-time, outstanding), a 12-month billed-vs-collected bar chart (Chart.js), and collected-by-category table. Verified live — tiles, chart, and category breakdown all render with real seeded data. **Management-reporting parity is now PRESENT** (revenue + aging + CSV export + retention analytics).

### Iteration 9 — DONE (smoke 45/45, billing 16/16)
- **Input validation on financial writes** (P2-7): `create_transaction` + `bulk_charge` now reject negative/non-numeric/absurd amounts, invalid `type`, and malformed dates via shared `_valid_amount`/`_parse_txn_date` helpers — closing a silent balance-corruption path. Audited the untrusted parent money paths (`claim_payment`, `create_donation`) — already validated. Added 6 validation regression checks.

### Iteration 10 — DONE (smoke 53/53)
- **Audited + verified the public self-registration flow** (the critical fall-enrollment path): confirmed no stored XSS (admin page escapes all fields), no mass assignment on approval, idempotent. Hardened: email-format validation on submit, and approval now filters to existing class IDs (prevents dangling enrollments that would 500 the roster). Added a full submit→queue→approve→create regression (7 checks).

### Iteration 11 — DONE (deletion/cascade integrity audit)
- **Audited all 30 DELETE endpoints + cascade behavior** (see the Deletion section): sound. Containers soft-delete; family/class aren't deletable; the one hard-delete-with-dependents cleans up first (verified empirically — 0 orphaned orders). No cascade/orphan bug despite SQLite FK enforcement being off. This clears the last major server-side risk area I hadn't checked.

### Iteration 12 — DONE (verified live)
- **Staff UX: leads add flow → modal.** The New Lead flow was 5 chained browser `prompt()` dialogs; replaced with one on-brand modal form (name required, email/phone/interest/source). Verified live end-to-end (POST 201, lead appears in list). node-checked clean.

### Iteration 13 — DONE (verified live)
- **Staff UX: all 3 Performance Company flows → modals** (new company / audition / performance). The audition & performance flows were 4–5 chained prompts *and* made staff type a number to pick a company from a text list — replaced with modal forms and a real company dropdown. Verified live (performance create POST 201, dropdown populated); node-checked clean. Built with a reusable Jinja `{% call modal(...) %}` macro to speed remaining conversions.

### Iteration 14 — DONE (verified live)
- **Staff UX: whole pending-payments page → modals** (apply-late-fees, new-payment-plan, reject-payment). The payment-plan flow was 5 chained prompts incl. a type-a-number student picker → now a modal with a student dropdown (shows each student's balance). Verified live end-to-end (plan create POST 201, dropdown populated with 24 students). This clears a fall-critical page of all `prompt()`s. node-checked clean.

### Iteration 15 — DONE (smoke 57/57)
- **Audited the email/SMS message-blast flow** (studio→families comms — see the Email/SMS section): sound — correct de-duplicated recipient resolution, graceful degradation when SMTP is unconfigured (saves + returns emails to copy). Hardened: non-numeric `recipient_filter` → 400 (was a potential 500). Added 5 regression checks (resolve/degrade/validate/parent-blocked).

### Iteration 16 — DONE
- **Wired the QA harnesses into CI** (`.github/workflows/tests.yml`): both harnesses (57 + 16 checks) run on every push/PR against the prod dependency set. Verified in a clean CI-mirror venv — 57/57 + 16/16. Makes the whole session's security/billing/flow verification a durable regression gate instead of a one-time pass. (Activates when the branch is pushed.)

### Iteration 17 — DONE (smoke 57/57)
- **Accessibility: labeled every icon-only button app-wide** (~23 buttons across 12 templates — delete/edit/close/remove/move/copy) with `aria-label` + `aria-hidden` on the decorative icons. Screen-reader users now get names for all icon controls, not just the base shell. Verified: 0 unlabeled icon-only buttons; all templates compile; JS-heavy pages node-check clean. (A batch script mislabeled 2 text buttons — caught via a "label on a text-bearing button" scan and fixed.)

### Iteration 18 — DONE
- **Wrote the go-live runbook** ([GO-LIVE.md](GO-LIVE.md)): the ordered, executable launch sequence — required secrets (SECRET_KEY, admin password) → merge/deploy → post-deploy smoke test → optional client-side config (SMTP, Square, Zelle, Twilio, registration, cron), grounded in the app's actual config mechanisms. Turns the whole audit into an actionable launch plan. (Considered SRI/CDN hardening (P3-4) but left it: the Tailwind Play CDN can't take a stable SRI hash, and a real Tailwind build is a large refactor that would risk the design system — not worth it for a low-likelihood CDN-compromise risk.)

### Iteration 19 — DONE (smoke 61/61)
- **Verified taking attendance end-to-end** (the most-used fall feature — see the Attendance section): UI renders, mark-present persists (201), toggle-off removes (200), parents blocked (403). Added a 4-check regression. This was the last core fall flow I'd loaded pages around but not actually exercised.

### Iteration 20 — DONE (smoke 66/66)
- **Verified waiver signing end-to-end** (enrollment flow — see the Waiver section): parent signs own child's waiver (200) + reads back signed; typed-signature required; decline rules enforced (mandatory→400, opt-out→200); other-family still blocked (403). Added a 5-check regression. With this + attendance, every parent-and-staff flow a fall session touches is now exercised, not just code-reviewed.

### Iteration 21 — DONE (verified live)
- **Staff UX: makeups admin page → modals.** The log-makeup flow was 5 chained prompts incl. a *type-an-ID* dancer picker and type-a-class-ID pickers; now a modal with dancer + class dropdowns. The schedule-makeup flow (2 prompts) is a modal too. Verified live (log-makeup POST 201, dropdown populated with 24 students); node-checked clean. Makeups is used *during* the fall session (scheduling parent makeup requests), so this one mattered.

### Iteration 22 — DONE (verified live)
- **Staff UX: donations admin → modal.** The record-donation flow (4 prompts) is now a modal (donor name/email, amount, method dropdown). Verified live (POST 201). Donations are recorded *during* the fall/foundation season, so this was the last fall-used prompt flow — **every flow the studio touches in fall is now prompt-free.**

### Remaining for next iterations
- P1-2 autopay/cards-on-file (biggest parity build — needs Thomas's go-ahead, it's a feature), ~24 remaining staff-side `prompt()` flows → modals — **all spring/off-season now** (recital, waivers-admin, skills); every fall-used flow is prompt-free. P3-4 SRI (deferred — see above) prompt() flows, P2-3 toast unify, P2-4 aria-labels, P2-5 cron token constant-time check, P2 Square PARTIALLY_PAID semantics, P3s. Full Jackrabbit parity matrix still to expand.
