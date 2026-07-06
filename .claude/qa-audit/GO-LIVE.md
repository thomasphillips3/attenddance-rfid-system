# AttenDANCE — Go-Live Runbook (Fall Session)

The concrete steps to take the hardened `fix/api-authorization-and-secret-key`
branch live for the fall session. Do them in order. Full findings behind each
item are in [ASSESSMENT.md](ASSESSMENT.md). Once deployed, hand
[FALL-SETUP.md](FALL-SETUP.md) to Carollette — it's the operator runbook for
standing up the fall session (classes, tuition, enrollment, first billing).

---

## 1. Required before deploy — do NOT skip (5 min)

These two are hard blockers. The app will refuse to boot in production without
a real `SECRET_KEY`, and the seeded admin password is publicly known.

- [x] **Set a real signing secret** (also encrypts the Square token at rest):
  ```
  fly secrets set SECRET_KEY=$(python3 -c 'import secrets;print(secrets.token_hex(32))')
  ```
  ✅ **Done 2026-07-05** — `flyctl secrets list` shows SECRET_KEY Deployed; app
  restarted healthy (200). Square wasn't configured, so nothing encrypted got
  orphaned.

- [x] **Change the admin password.** ✅ done 2026-07-06. After deploy, log in as `admin` and go to
  `/auth/change-password`. (Until then the default `admin123` is public.) The
  demo-credentials box on the login page auto-hides in production.
- **Demo parent self-cleans — no action needed.** The prod DB currently has the
  `parent-demo`/`parent123` account linked to a real student; on the first boot
  of this branch, production automatically deactivates it (and the seed endpoint
  refuses to recreate it outside dev). Verify in logs: "Disabled demo parent
  account".

---

## 2. Ship the branch (10 min)

- [x] ✅ Merged via PR #1 (2026-07-06, CI green). Review the branch: the P0 security fixes (IDOR, SECRET_KEY, CSRF), the
  parent-portal JS repair, the billing fixes, the new reports, and CI. Merge to
  `main`.
- ✅ **Deploy rehearsal already done (2026-07-06):** the production image was
  built and run locally — fail-closed boot without SECRET_KEY, clean boot with
  it, login through the proxied CSRF shape, Secure/HttpOnly/Lax cookie, HSTS,
  JSON API errors, and the demo-parent self-clean were all verified against the
  live container.
- [x] Deploy to Fly ✅ done 2026-07-06 (`flyctl deploy`).
- [x] **Confirm it booted** ✅ verified (boot logs clean, demo-parent self-clean fired) — if you forgot step 1, the logs will show
  `RuntimeError: Refusing to start in production ... SECRET_KEY`. That's the
  fail-closed guard working; set the secret and redeploy.

---

## 3. Post-deploy smoke test (5 min)

- [x] Log in as admin; open Dashboard, Students, Payments, Calendar — all load. ✅ verified live 2026-07-06.
- [x] Parent portal: the demo parent is deleted (test data cleared 2026-07-06); verify with the first real parent account
  its sections (this was fully broken before the JS fix — it must show payment
  methods, makeups, etc., not a static shell).
- [x] Open `/reports/revenue` and `/reports/aging` — charts + tables render. ✅ verified live 2026-07-06.

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
  the Square dashboard. **The signature key is required** — the webhook now
  *fails closed*: without it, Square "paid" events are ignored (not recorded), so
  a forged event can't credit an account. Until the key is set, reconcile Square
  payments manually via `/pending-payments`.
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
- **SQLite runs in WAL mode** (enabled automatically — for concurrency under the
  gthread worker + background send threads). After the first boot you'll see
  `attendance.db-wal` and `attendance.db-shm` next to the DB on the volume;
  that's expected. The **Download backup** button uses SQLite's online backup
  API, so it captures a consistent snapshot including any WAL data — no manual
  checkpoint needed.
- **Backups — the whole studio is one file, so keep copies.** Two layers:
  1. **Manual (do this regularly):** `/settings` → **Data & Backup** → **Download
     backup** pulls a complete, consistent snapshot of everything (families,
     ledger, recitals) as one `.db` file. Save it off-Fly (your computer, Google
     Drive). Do it before any big change and, say, monthly. This is also your
     data-portability path if you ever leave AttenDANCE.
  2. **Automatic — ✅ verified live (2026-07-06):** Fly is taking daily snapshots
     of `attenddance_data` (`vol_vjy1k1q7zjk60y9v`) — 5 on record, one per day.
     ✅ **Retention raised to 60 days (Thomas, 2026-07-06)** via
     `fly volumes update vol_vjy1k1q7zjk60y9v --snapshot-retention 60`.
     The manual download is still the one you control — don't rely on Fly
     snapshots alone.
- **Restore recipes (hope you never need them):**
  - *From a Fly snapshot* (volume/machine loss): list snapshots
    (`fly volumes snapshots list vol_vjy1k1q7zjk60y9v`), then
    `fly volumes create attenddance_data --snapshot-id vs_… --region lax`;
    destroy the old machine/volume and `fly deploy` — the new machine mounts the
    restored volume by its `attenddance_data` name from `fly.toml` `[mounts]`.
  - *From a downloaded `.db`* (logical restore / corruption): stop the machine,
    `fly ssh sftp shell` → `put backup.db /data/attendance.db` (also delete any
    stale `attendance.db-wal`/`-shm` next to it), restart.
- **Regression safety:** every push/PR runs the full check suite (access control,
  billing math, input robustness, empty-state, the fall flows) via
  `.github/workflows/tests.yml`.

---

## What is intentionally NOT in this launch

- **Auto-pay / cards-on-file** — the one Jackrabbit parity gap left. Fall runs on
  manual collection (Zelle/Cash App reconciliation + one-off Square invoices) +
  the A/R aging report to chase balances. Auto-charging saved cards is a separate
  feature build — decision-ready scope in [AUTOPAY-SCOPE.md](AUTOPAY-SCOPE.md)
  (~3–4 days, recommend building it as the first post-launch project). Greenlight
  it when you want it.
- **RFID card-tap check-in** — the card reader can't reach the Fly deployment
  (it reads in-process and writes to a local DB; there's no remote-scan
  endpoint). **Check-in at launch = the take-attendance page on a
  tablet/laptop** — teachers have access, works today. Do NOT boot the old Pi
  setup alongside Fly: it would check dancers into its own local database and
  fork attendance away from billing. If card-tap matters for fall, the bridge
  (a token-authenticated scan endpoint + a thin Pi poster with offline queueing)
  is ~a half-day plus hardware testing — ask for it.
