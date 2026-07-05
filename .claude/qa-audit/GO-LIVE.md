# AttenDANCE — Go-Live Runbook (Fall Session)

The concrete steps to take the hardened `fix/api-authorization-and-secret-key`
branch live for the fall session. Do them in order. Full findings behind each
item are in [ASSESSMENT.md](ASSESSMENT.md).

---

## 1. Required before deploy — do NOT skip (5 min)

These two are hard blockers. The app will refuse to boot in production without
a real `SECRET_KEY`, and the seeded admin password is publicly known.

- [ ] **Set a real signing secret** (also encrypts the Square token at rest):
  ```
  fly secrets set SECRET_KEY=$(python3 -c 'import secrets;print(secrets.token_hex(32))')
  ```
  Safe to set now — Square isn't configured, so nothing encrypted gets orphaned.

- [ ] **Change the admin password.** After deploy, log in as `admin` and go to
  `/auth/change-password`. (Until then the default `admin123` is public.) The
  demo-credentials box on the login page auto-hides in production.

---

## 2. Ship the branch (10 min)

- [ ] Review the branch: the P0 security fixes (IDOR, SECRET_KEY, CSRF), the
  parent-portal JS repair, the billing fixes, the new reports, and CI. Merge to
  `main`.
- [ ] Deploy to Fly (`flyctl deploy`, or your existing push-to-deploy flow).
- [ ] **Confirm it booted** — if you forgot step 1, the logs will show
  `RuntimeError: Refusing to start in production ... SECRET_KEY`. That's the
  fail-closed guard working; set the secret and redeploy.

---

## 3. Post-deploy smoke test (5 min)

- [ ] Log in as admin; open Dashboard, Students, Payments, Calendar — all load.
- [ ] Open a parent account (or the demo parent) and confirm the portal loads
  its sections (this was fully broken before the JS fix — it must show payment
  methods, makeups, etc., not a static shell).
- [ ] Open `/reports/revenue` and `/reports/aging` — charts + tables render.

---

## 4. Client-side configuration (in the app UI, as time allows)

None of these block launch — the app degrades gracefully (e.g. receipts save
with a "copy these emails" fallback until SMTP is set). Turn them on as ready.

- [ ] **Email (receipts, reminders, blasts).** Set as Fly secrets and redeploy:
  `MAIL_SERVER=smtp.gmail.com`, `MAIL_PORT=587`,
  `MAIL_USERNAME=LaShellesDance@gmail.com`, `MAIL_PASSWORD=<gmail app password>`.
  (Reply-To already defaults to LaShellesDance@gmail.com.)
- [ ] **Online card payments (Square).** `/settings` → enter access token +
  location ID → **Test Connection**. (Token is encrypted at rest.) For
  auto-reconcile, add the webhook signature key and register the webhook URL in
  the Square dashboard.
- [ ] **Zelle / Cash App.** `/settings` → upload the Zelle QR, set the Cash App
  tag. (These already work for manual reconciliation.)
- [ ] **SMS reminders (Twilio).** `/settings` → SMS section → SID, token, from-number.
- [ ] **Enrollment.** When you're ready for families to self-register, `/settings`
  → flip **registration open**. The public form is at `/register`.
- [ ] **Auto-reminders (optional).** `/settings` → set a `cron_token`, then point
  an external scheduler at `POST /api/cron/run` with that token to send monthly
  balance reminders automatically.

---

## 5. Good to know

- **Deploy sizing:** the Fly machine is 256 MB and runs **one** gunicorn gthread
  worker — do not raise `--workers` without raising memory (two workers OOM-kill
  and race on SQLite migrations). Migrations run automatically on boot.
- **Data lives on the Fly volume** (`/data/attendance.db`); settings are in the
  prod DB, not env — configure them through the UI, not local scripts.
- **Regression safety:** every push/PR runs 73 automated checks (access control,
  billing math, the fall flows) via `.github/workflows/tests.yml`.

---

## What is intentionally NOT in this launch

- **Auto-pay / cards-on-file** — the one Jackrabbit parity gap left. Fall runs on
  manual collection (Zelle/Cash App reconciliation + one-off Square invoices) +
  the A/R aging report to chase balances. Auto-charging saved cards is a separate
  feature build — decision-ready scope in [AUTOPAY-SCOPE.md](AUTOPAY-SCOPE.md)
  (~3–4 days, recommend building it as the first post-launch project). Greenlight
  it when you want it.
- A handful of spring-only staff screens (recital, waivers, skills) still use
  simple browser prompts for data entry — cosmetic, not used in fall.
