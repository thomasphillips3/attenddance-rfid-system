"""QA production-readiness harness for AttenDANCE.

Runtime checks that complement the static audit:
  1. Boot on a throwaway SQLite DB.
  2. Seed admin + two UNRELATED parent/student/family sets.
  3. IDOR probe: parent A must NOT be able to read/edit/delete parent B's child
     via the JSON API, and must not reach staff-only endpoints.
  4. Smoke: as admin, GET every no-arg route and assert no 500s.

Run:  RFID_ENABLED=false python3 tests/smoke_audit.py
Exit code 0 = all green, 1 = failures (prints a report).
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("RFID_ENABLED", "false")

# Point the app at a throwaway DB before importing config.
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"

from app import create_app, db  # noqa: E402
from app.models import User, Student, Family, ParentStudent  # noqa: E402

app = create_app("development")
app.config["WTF_CSRF_ENABLED"] = False
app.config["TESTING"] = True

results = []  # (severity, name, passed, detail)


def record(name, passed, detail="", severity="P1"):
    results.append((severity, name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"[{mark}] ({severity}) {name}" + (f" — {detail}" if detail and not passed else ""))


def seed():
    with app.app_context():
        # Two unrelated families, each with one parent + one child.
        fam_a = Family(name="Alpha Family")
        fam_b = Family(name="Beta Family")
        db.session.add_all([fam_a, fam_b])
        db.session.flush()

        child_a = Student(first_name="Ava", last_name="Alpha", family_id=fam_a.id,
                          parent_email="alpha-parent@x.com",
                          allergies="peanuts", special_needs="asthma")
        child_b = Student(first_name="Bo", last_name="Beta", family_id=fam_b.id,
                          parent_email="beta-parent@x.com",
                          allergies="shellfish", special_needs="epilepsy")
        db.session.add_all([child_a, child_b])
        db.session.flush()

        parent_a = User(username="parent_a", email="a@x.com", role="parent",
                        first_name="Pat", last_name="Alpha", is_active=True)
        parent_a.set_password("pw")
        parent_b = User(username="parent_b", email="b@x.com", role="parent",
                        first_name="Pat", last_name="Beta", is_active=True)
        parent_b.set_password("pw")
        db.session.add_all([parent_a, parent_b])
        db.session.flush()

        db.session.add_all([
            ParentStudent(parent_id=parent_a.id, student_id=child_a.id),
            ParentStudent(parent_id=parent_b.id, student_id=child_b.id),
        ])
        db.session.commit()
        return {
            "child_a": child_a.id, "child_b": child_b.id,
            "fam_a": fam_a.id, "fam_b": fam_b.id,
        }


def login(client, username, password):
    return client.post("/auth/login",
                       data={"username": username, "password": password},
                       follow_redirects=True)


def run_idor(ids):
    """Parent A acting on Parent B's child must be blocked (403/404)."""
    with app.test_client() as c:
        login(c, "parent_a", "pw")
        bid = ids["child_b"]
        fbid = ids["fam_b"]
        aid = ids["child_a"]

        # Positive: parent MUST still reach their own child + own data (no over-lock).
        for method, path, desc in [
            ("GET", f"/api/students/{aid}", "own child PII"),
            ("GET", f"/api/students/{aid}/ledger", "own child ledger"),
            ("GET", "/api/my-payments", "own payments"),
        ]:
            resp = c.open(path, method=method)
            ok = resp.status_code == 200
            record(f"Parent CAN access {desc} [{method} {path}] -> {resp.status_code}",
                   ok, f"got {resp.status_code}, expected 200", "P1")

        probes = [
            ("GET",    f"/api/students/{bid}",                 "read other child's PII"),
            ("PUT",    f"/api/students/{bid}",                 "edit other child"),
            ("DELETE", f"/api/students/{bid}",                 "deactivate other child"),
            ("GET",    f"/api/students/{bid}/ledger",          "read other child's ledger"),
            ("GET",    f"/api/students/{bid}/skills",          "read other child's skills"),
            ("GET",    f"/api/students/{bid}/waivers",         "read other child's waivers"),
            ("GET",    f"/api/students/{bid}/rules-status",    "read other child's rules status"),
            ("GET",    f"/api/students/{bid}/payment-plan",    "read other child's plan"),
            ("GET",    f"/api/families/{fbid}/ledger",         "read other family's ledger"),
        ]
        for method, path, desc in probes:
            resp = c.open(path, method=method, json={} if method != "GET" else None)
            blocked = resp.status_code in (401, 403, 404)
            record(f"IDOR blocked: {desc} [{method} {path}] -> {resp.status_code}",
                   blocked, f"got {resp.status_code}, expected 401/403/404", "P0")

        # Parent must not reach staff-only endpoints (reads). Comprehensive sweep
        # of the whole staff-only GET surface (not a spot-check) — every one of
        # these leaks studio-wide or other-family data if it 200s for a parent.
        staff_only = [
            "/api/students",              # full roster
            "/api/transactions",          # all money
            "/api/staff",                 # all staff accounts
            "/api/families",              # all families
            "/api/messages",              # all sent messages
            "/api/balances",              # every family's balance
            "/api/attendance",            # attendance records
            "/api/attendance/today",      # today's attendance
            "/api/dashboard/stats",       # studio stats
            "/api/reports/aging",         # A/R aging report
            "/api/reports/revenue",       # revenue report
            "/api/reports/students.csv",  # roster export
            "/api/reports/transactions.csv",  # money export
            "/api/leads",                 # sales pipeline (PII of prospects)
            "/api/donations",             # all donations
            "/api/locations",            # venues + internal notes/phone
            "/api/classes",               # full class list (instructors, rosters)
            "/api/skills",                # skill catalog
            "/api/costumes",              # costume catalog
            "/api/recurring-charges",     # every recurring charge
            "/api/pending-payments",      # every family's reported payments
            "/api/registrations",         # every enrollment request (PII)
            "/api/audit-log",             # the full audit trail
            "/api/analytics/retention",   # retention analytics
            "/api/rfid/logs",             # every check-in
            "/api/timeclock/report",      # staff payroll
            "/api/waivers/compliance",    # every family's waiver status
            "/api/settings/payments",     # payment config (may carry secrets)
        ]
        for path in staff_only:
            resp = c.get(path)
            blocked = resp.status_code in (401, 403, 404)
            record(f"Parent blocked from staff read [GET {path}] -> {resp.status_code}",
                   blocked, f"got {resp.status_code}", "P0")

        # The nav-badge count endpoints intentionally 200 for parents but MUST
        # return a safe stub (0), never the real studio count.
        for path in ("/api/pending-payments/count", "/api/registrations/count"):
            j = c.get(path).get_json() or {}
            record(f"Count endpoint returns safe stub to parent [{path}] -> {j}",
                   j.get("count") == 0, f"leaked real count: {j}", "P2")

        # Parent must not perform staff-only WRITES (fabricate money, email blasts).
        forbidden_writes = [
            ("POST", "/api/transactions", "fabricate a payment/charge"),
            ("POST", "/api/transactions/bulk-charge", "bulk-charge families"),
            ("POST", "/api/messages", "send studio-wide email blast"),
            ("POST", "/api/recurring-charges", "create recurring charge"),
            ("POST", "/api/classes", "create a class"),
        ]
        for method, path, desc in forbidden_writes:
            resp = c.open(path, method=method, json={})
            blocked = resp.status_code in (401, 403)
            record(f"Parent write BLOCKED: {desc} [{method} {path}] -> {resp.status_code}",
                   blocked, f"got {resp.status_code}, expected 403", "P0")

        # Parent-ALLOWED writes must NOT be blocked by the guard (may 400 on bad
        # body, but must not 403). This guards against over-locking the portal.
        allowed_writes = [
            ("POST", "/api/payments/claim", "report a payment"),
            ("POST", "/api/donations", "make a donation"),
        ]
        for method, path, desc in allowed_writes:
            resp = c.open(path, method=method, json={})
            not_locked = resp.status_code != 403
            record(f"Parent-allowed write reachable: {desc} [{method} {path}] -> {resp.status_code}",
                   not_locked, f"got 403 — guard over-locked the portal", "P1")


def run_prod_security_config():
    """Guard the production security posture from regression: (1) the fail-closed
    SECRET_KEY guard refuses a missing/default key but boots on a strong one, and
    (2) both the session and the 'remember me' cookies get Secure + HttpOnly +
    SameSite in production. The remember cookie is a long-lived credential, so it
    must be hardened like the session cookie.

    SECRET_KEY is read at config-import time, so this must run in fresh
    subprocesses with the env set before import — an in-process test can't change
    the frozen value (and would give a false result)."""
    import subprocess

    def _boot(secret_key):
        """Boot production in a clean interpreter with the given SECRET_KEY.
        Returns (rc, stdout). rc != 0 means the fail-closed guard refused."""
        snippet = (
            "import os, json\n"
            "from app import create_app\n"
            "app = create_app('production')\n"
            "keys = ['SESSION_COOKIE_SECURE','SESSION_COOKIE_HTTPONLY','SESSION_COOKIE_SAMESITE',"
            "'REMEMBER_COOKIE_SECURE','REMEMBER_COOKIE_HTTPONLY','REMEMBER_COOKIE_SAMESITE']\n"
            "print(json.dumps({k: app.config.get(k) for k in keys}))\n"
        )
        env = dict(os.environ)
        env["SECRET_KEY"] = secret_key
        env["RFID_ENABLED"] = "false"
        env["DATABASE_URL"] = f"sqlite:///{tempfile.NamedTemporaryFile(suffix='.db').name}"
        p = subprocess.run([sys.executable, "-c", snippet], capture_output=True,
                           text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           env=env, timeout=60)
        return p.returncode, p.stdout.strip()

    # Default key must be refused (fail closed).
    rc, _ = _boot("dev-secret-key-change-in-production-12345")
    record("Prod refuses a default SECRET_KEY (fail closed)", rc != 0,
           "prod booted with the known default key", "P0")

    # A strong key must be accepted, so the studio can actually deploy.
    import secrets as _secrets
    rc, out = _boot(_secrets.token_hex(32))
    record("Prod boots with a strong SECRET_KEY", rc == 0,
           f"guard too strict, rejected a real key (rc={rc})", "P0")
    if rc == 0 and out:
        import json as _json
        cfg = _json.loads(out.splitlines()[-1])
        want = {
            "SESSION_COOKIE_SECURE": True, "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_SAMESITE": "Lax", "REMEMBER_COOKIE_SECURE": True,
            "REMEMBER_COOKIE_HTTPONLY": True, "REMEMBER_COOKIE_SAMESITE": "Lax",
        }
        for k, exp in want.items():
            record(f"Prod cookie hardening: {k} == {exp!r} (got {cfg.get(k)!r})",
                   cfg.get(k) == exp, f"got {cfg.get(k)!r}", "P2")


def run_csrf():
    """Cross-origin writes must be blocked; same-origin writes must pass through."""
    with app.test_client() as c:
        login(c, "admin", "admin123")
        # Foreign Origin on a state-changing request -> 403.
        resp = c.post("/api/classes", json={},
                      headers={"Origin": "https://evil.example.com"})
        record(f"Cross-origin write blocked [Origin: evil] -> {resp.status_code}",
               resp.status_code == 403, f"got {resp.status_code}, expected 403", "P1")
        # Same-origin Origin -> not blocked by the CSRF guard (may 400 on body).
        resp = c.post("/api/classes", json={},
                      headers={"Origin": "http://localhost"})
        record(f"Same-origin write not CSRF-blocked -> {resp.status_code}",
               resp.status_code != 403 or b'Cross-origin' not in resp.data,
               f"got 403 cross-origin on same-origin request", "P1")
        # No Origin/Referer (e.g. server client) -> allowed through the guard.
        resp = c.post("/api/classes", json={})
        record(f"No-Origin write not CSRF-blocked -> {resp.status_code}",
               b'Cross-origin' not in resp.data, "blocked a no-Origin request", "P2")


def run_multichild_invite_merge():
    """Sibling families get one invite per child. Registering the 2nd+ invite
    with the same email must MERGE the dancer onto the parent's existing account
    (one login shows all kids), not 500 on the unique-email constraint."""
    from app.models import User, Student, ParentStudent

    with app.app_context():
        k1 = Student(first_name="Sib", last_name="One")
        k2 = Student(first_name="Sib", last_name="Two")
        db.session.add_all([k1, k2])
        db.session.flush()
        for code, kid in (("MCODE1", k1), ("MCODE2", k2)):
            u = User(username=f"parent-{code}", email=f"invite-{code}@pending.local",
                     first_name="Pending", last_name="Parent", role="parent",
                     is_active=False, invite_code=code, password_hash="x")
            db.session.add(u)
            db.session.flush()
            db.session.add(ParentStudent(parent_id=u.id, student_id=kid.id))
        db.session.commit()

    with app.test_client() as c:
        r1 = c.post("/auth/register", data={"invite_code": "MCODE1", "first_name": "Sib",
                    "last_name": "Parent", "email": "sibs@x.com", "password": "pw"})
        record(f"Sibling invite 1 registers -> {r1.status_code}", r1.status_code in (200, 302),
               f"got {r1.status_code}", "P1")
    with app.test_client() as c:
        r2 = c.post("/auth/register", data={"invite_code": "MCODE2", "first_name": "Sib",
                    "last_name": "Parent", "email": "sibs@x.com", "password": "pw"},
                    follow_redirects=False)
        record(f"Sibling invite 2 (same email) merges, no 500 -> {r2.status_code}",
               r2.status_code in (200, 302), f"got {r2.status_code} (500=the bug)", "P1")
    with app.app_context():
        accts = User.query.filter_by(email="sibs@x.com", is_active=True).all()
        one_acct = len(accts) == 1
        both_kids = one_acct and len({s.last_name for s in accts[0].get_children()} | {"One", "Two"}) == 2 \
            and len(accts[0].get_children()) == 2
        record("Both siblings under one account", one_acct and both_kids,
               f"accounts={len(accts)}, kids={[s.full_name for s in accts[0].get_children()] if accts else []}", "P1")
        record("No orphaned invite accounts", User.query.filter(User.invite_code.isnot(None)).count() == 0,
               "leftover invites", "P2")


def run_square_webhook(ids):
    """Square auto-reconcile: a PARTIALLY_PAID event must be ignored (else it
    books the whole invoice + blocks the final PAID event); a PAID event records
    the full amount once and is idempotent. No signature key set -> unsigned."""
    from app.models import SquareInvoice, Transaction

    sid = ids["child_a"]
    with app.app_context():
        inv = SquareInvoice(student_id=sid, invoice_id="sqinv_test_1",
                            amount_cents=8000, status="SENT")
        db.session.add(inv)
        db.session.commit()

    def event(status):
        return {"type": "invoice.updated",
                "data": {"object": {"invoice": {"id": "sqinv_test_1", "status": status}}}}

    with app.test_client() as c:  # no login — Square calls this
        r = c.post("/api/webhooks/square", json=event("PARTIALLY_PAID"))
        with app.app_context():
            n = Transaction.query.filter(Transaction.description.like("%sqinv_test_1%")).count()
        record(f"PARTIALLY_PAID ignored (no transaction) -> {r.get_json()}",
               (r.get_json() or {}).get("status") == "ignored" and n == 0, f"txns={n}", "P2")

        r = c.post("/api/webhooks/square", json=event("PAID"))
        with app.app_context():
            txns = Transaction.query.filter(Transaction.description.like("%sqinv_test_1%")).all()
        record(f"PAID records the full $80 once -> {r.get_json()}",
               (r.get_json() or {}).get("status") == "recorded" and len(txns) == 1
               and float(txns[0].amount) == 80.0, f"txns={[float(t.amount) for t in txns]}", "P1")

        r = c.post("/api/webhooks/square", json=event("PAID"))  # duplicate
        with app.app_context():
            n = Transaction.query.filter(Transaction.description.like("%sqinv_test_1%")).count()
        record(f"Duplicate PAID is idempotent (still 1) -> {r.get_json()}",
               (r.get_json() or {}).get("status") == "already_recorded" and n == 1, f"txns={n}", "P1")


def run_reconciliation(ids):
    """The core fall tuition-collection flow: parent claims a payment -> admin
    confirms -> a payment Transaction is created and the balance drops. Confirm
    is idempotent; a parent can't confirm their own claim."""
    from app.models import Transaction, PendingPayment
    from app.helpers import calc_balance

    sid = ids["child_a"]
    with app.app_context():
        db.session.add(Transaction(student_id=sid, type="charge", amount=100,
                                   category="tuition", payment_method="n/a", description="fall tuition"))
        db.session.commit()
        start_bal = calc_balance(sid)["balance"]

    # Parent claims a $60 Zelle payment
    with app.test_client() as c:
        login(c, "parent_a", "pw")
        r = c.post("/api/payments/claim",
                   json={"student_id": sid, "amount": 60, "method": "zelle", "reference": "abc123"})
        record(f"Parent claims a payment -> {r.status_code}", r.status_code in (200, 201),
               r.get_data(as_text=True)[:60], "P1")

    with app.app_context():
        pend = PendingPayment.query.filter_by(student_id=sid, status="pending").order_by(
            PendingPayment.id.desc()).first()
        pid = pend.id if pend else None
    record("Claim created a pending payment", pid is not None, "", "P1")

    if pid:
        # A parent must NOT be able to confirm (admin-only)
        with app.test_client() as c:
            login(c, "parent_a", "pw")
            r = c.post(f"/api/pending-payments/{pid}/confirm", json={})
            record(f"Parent cannot confirm a payment -> {r.status_code}",
                   r.status_code == 403, f"got {r.status_code}", "P0")
        # Admin confirms -> creates the payment transaction, reduces balance
        with app.test_client() as c:
            login(c, "admin", "admin123")
            r = c.post(f"/api/pending-payments/{pid}/confirm", json={"category": "tuition"})
            record(f"Admin confirms the payment -> {r.status_code}", r.status_code == 200,
                   r.get_data(as_text=True)[:60], "P1")
            with app.app_context():
                new_bal = calc_balance(sid)["balance"]
                pay = Transaction.query.filter_by(student_id=sid, type="payment").count()
            record(f"Balance dropped by $60 ({start_bal:.2f} -> {new_bal:.2f})",
                   round(start_bal - new_bal, 2) == 60.0 and pay >= 1, "", "P1")
            # double-confirm is rejected
            r2 = c.post(f"/api/pending-payments/{pid}/confirm", json={})
            record(f"Double-confirm rejected -> {r2.status_code}", r2.status_code == 400,
                   f"got {r2.status_code}", "P1")


def run_enrollment(ids):
    """Class enrollment (fall-critical): enroll a student, dedup a repeat,
    unenroll, and confirm counts. Parents can't enroll."""
    from datetime import time as _time
    from app.models import DanceClass, ClassEnrollment, User

    with app.app_context():
        admin = User.query.filter_by(username="admin").first()
        dc = DanceClass(name="Ballet I", day_of_week=0, start_time=_time(17, 0),
                        end_time=_time(18, 0), instructor_id=admin.id, max_students=10)
        db.session.add(dc)
        db.session.commit()
        cid = dc.id
    sid = ids["child_a"]

    with app.test_client() as c:
        login(c, "admin", "admin123")
        r = c.post(f"/api/classes/{cid}/enroll", json={"student_id": sid})
        record(f"Enroll a student -> {r.status_code}", r.status_code == 201, r.get_data(as_text=True)[:60], "P1")
        # duplicate enroll is skipped, not 500
        r2 = c.post(f"/api/classes/{cid}/enroll", json={"student_id": sid})
        d2 = r2.get_json() or {}
        record(f"Duplicate enroll skipped (no 500) -> {r2.status_code}",
               r2.status_code == 201 and d2.get("skipped"), str(d2)[:60], "P1")
        with app.app_context():
            eid = ClassEnrollment.query.filter_by(class_id=cid, student_id=sid, is_active=True).first().id
            count = ClassEnrollment.query.filter_by(class_id=cid, is_active=True).count()
        record(f"Exactly one active enrollment (got {count})", count == 1, "", "P1")
        # unenroll
        r3 = c.delete(f"/api/enrollments/{eid}")
        record(f"Unenroll -> {r3.status_code}", r3.status_code == 200, "", "P2")
        with app.app_context():
            still = ClassEnrollment.query.filter_by(class_id=cid, is_active=True).count()
        record(f"Unenroll removed the active enrollment (now {still})", still == 0, "", "P1")

        # Robustness: a garbage/nonexistent id must not 500 or create an orphan.
        rg = c.post(f"/api/classes/{cid}/enroll", json={"student_id": "xyz"})
        record(f"Enroll garbage student_id handled (no 500) -> {rg.status_code}",
               rg.status_code < 500, f"got {rg.status_code}", "P2")
        wn = c.post(f"/api/classes/{cid}/waitlist", json={"student_id": 999999})
        record(f"Waitlist nonexistent student -> {wn.status_code} (404, no orphan)",
               wn.status_code == 404, f"got {wn.status_code}", "P2")
        wg = c.post(f"/api/classes/{cid}/waitlist", json={"student_id": "xyz"})
        record(f"Waitlist garbage student_id -> {wg.status_code} (400)",
               wg.status_code == 400, f"got {wg.status_code}", "P3")
        # Waitlist a real student, confirm the page renders (no orphan 500), promote.
        bid = ids["child_b"]
        wr = c.post(f"/api/classes/{cid}/waitlist", json={"student_id": bid})
        record(f"Waitlist a real student -> {wr.status_code}", wr.status_code == 201,
               wr.get_data(as_text=True)[:60], "P2")
        gw = c.get(f"/api/classes/{cid}/waitlist")
        record(f"Waitlist page renders (no orphan 500) -> {gw.status_code}",
               gw.status_code == 200, f"got {gw.status_code}", "P2")
        with app.app_context():
            from app.models import WaitlistEntry
            wid = WaitlistEntry.query.filter_by(class_id=cid, student_id=bid, status='waiting').first().id
        pr = c.post(f"/api/waitlist/{wid}/promote")
        with app.app_context():
            promoted = ClassEnrollment.query.filter_by(class_id=cid, student_id=bid, is_active=True).count()
        record(f"Promote from waitlist enrolls the student -> {pr.status_code}, enrolled={promoted}",
               pr.status_code == 200 and promoted == 1, f"status={pr.status_code} enrolled={promoted}", "P2")
    with app.test_client() as c:
        login(c, "parent_a", "pw")
        r = c.post(f"/api/classes/{cid}/enroll", json={"student_id": sid})
        record(f"Parent cannot enroll -> {r.status_code}", r.status_code == 403, f"got {r.status_code}", "P0")


def run_deactivation_revokes_session():
    """Deactivating an account must revoke access immediately, not only block
    fresh logins — a just-fired teacher shouldn't keep their live session."""
    from app.models import User

    with app.app_context():
        u = User(username="tempteach", email="tempteach@x.com", first_name="T",
                 last_name="R", role="teacher", is_active=True)
        u.set_password("pw")
        db.session.add(u)
        db.session.commit()
        uid = u.id

    with app.test_client() as c:
        login(c, "tempteach", "pw")
        record(f"Active staff can reach a protected page -> {c.get('/students').status_code}",
               c.get("/students").status_code == 200, "", "P2")
        with app.app_context():
            User.query.filter_by(id=uid).update({"is_active": False})
            db.session.commit()
        r = c.get("/students", follow_redirects=False)
        record(f"Deactivated mid-session is revoked -> {r.status_code}", r.status_code == 302,
               f"got {r.status_code} (200 = still had access)", "P2")


def run_password_reset():
    """Self-service password reset: request page degrades gracefully without
    SMTP, the signed token resets the password, and old creds stop working."""
    from app.auth.routes import _reset_serializer

    with app.test_client() as c:
        record(f"Forgot-password page renders -> {c.get('/auth/forgot-password').status_code}",
               c.get('/auth/forgot-password').status_code == 200, "", "P2")
        r = c.post('/auth/forgot-password', data={'email': 'a@x.com'}, follow_redirects=True)
        record("Forgot-password degrades gracefully without SMTP",
               'contact the studio' in r.get_data(as_text=True).lower(), "no fallback message", "P2")

    with app.app_context():
        from app.models import User
        uid = User.query.filter_by(email='a@x.com').first().id
        token = _reset_serializer().dumps(uid)
        bad = token[:-3] + 'zzz'

    with app.test_client() as c:
        record(f"Reset page with valid token -> {c.get('/auth/reset-password/'+token).status_code}",
               c.get('/auth/reset-password/' + token).status_code == 200, "", "P1")
    with app.test_client() as c:
        record(f"Invalid reset token redirected -> {c.get('/auth/reset-password/'+bad).status_code}",
               c.get('/auth/reset-password/' + bad, follow_redirects=False).status_code == 302, "", "P2")
    with app.test_client() as c:
        rr = c.post('/auth/reset-password/' + token,
                    data={'password': 'brandnewpw', 'confirm_password': 'brandnewpw'},
                    follow_redirects=False)
        record(f"Reset sets a new password -> {rr.status_code}", rr.status_code == 302, "", "P1")
    with app.test_client() as c:  # fresh client (not logged in)
        ok = c.post('/auth/login', data={'username': 'a@x.com', 'password': 'brandnewpw'},
                    follow_redirects=False)
        record(f"New password works after reset -> {ok.status_code}", ok.status_code == 302, "", "P1")
    with app.test_client() as c:  # fresh client — old password must now fail
        old = c.post('/auth/login', data={'username': 'a@x.com', 'password': 'pw'},
                     follow_redirects=False)
        record(f"Old password rejected after reset -> {old.status_code}", old.status_code == 200,
               f"got {old.status_code} (302 = old pw still works!)", "P1")
    # restore parent_a's password so later tests still log in
    with app.app_context():
        from app.models import User
        u = User.query.filter_by(email='a@x.com').first()
        u.set_password('pw')
        db.session.commit()


def run_login_by_email():
    """Invited parents get an auto-generated `parent-<code>` username they never
    see and register with an email — so login MUST accept email, or they're
    locked out after logging out. Staff keep username login."""
    with app.test_client() as c:
        # parent_a was seeded with email a@x.com
        r = c.post("/auth/login", data={"username": "a@x.com", "password": "pw"},
                   follow_redirects=False)
        record(f"Login by email works -> {r.status_code}", r.status_code == 302,
               f"got {r.status_code} (302=success)", "P1")
    with app.test_client() as c:
        r = c.post("/auth/login", data={"username": "parent_a", "password": "pw"},
                   follow_redirects=False)
        record(f"Login by username still works -> {r.status_code}", r.status_code == 302,
               f"got {r.status_code}", "P1")
    with app.test_client() as c:
        r = c.post("/auth/login", data={"username": "nobody@x.com", "password": "pw"},
                   follow_redirects=False)
        record(f"Login with unknown email rejected -> {r.status_code}", r.status_code == 200,
               f"got {r.status_code}", "P2")


def run_waiver_signing(ids):
    """A parent signs their OWN child's waiver end-to-end (enrollment flow):
    signature records + reads back as signed; decline rules enforced."""
    from app.models import WaiverTemplate

    with app.app_context():
        mandatory = WaiverTemplate(title="Liability Waiver", body="I agree.",
                                   allow_decline=False, is_active=True)
        optional = WaiverTemplate(title="Photo Release", body="Photos ok?",
                                  allow_decline=True, is_active=True)
        db.session.add_all([mandatory, optional])
        db.session.commit()
        mid, oid = mandatory.id, optional.id

    sid = ids["child_a"]
    with app.test_client() as c:
        login(c, "parent_a", "pw")
        # sign the mandatory waiver for own child
        r = c.post(f"/api/students/{sid}/waivers/{mid}/sign",
                   json={"signed_name": "Pat Alpha", "consent": True})
        record(f"Parent signs own child's waiver -> {r.status_code}", r.status_code == 200,
               f"got {r.status_code}: {r.get_data(as_text=True)[:80]}", "P1")
        # reads back as signed
        data = c.get(f"/api/students/{sid}/waivers").get_json() or {}
        signed = next((w for w in data.get("waivers", []) if w["id"] == mid), {})
        record("Signed waiver reads back as signed", signed.get("signed") is True, str(signed)[:80], "P1")
        # empty signature rejected
        r = c.post(f"/api/students/{sid}/waivers/{mid}/sign", json={"signed_name": ""})
        record(f"Waiver requires a typed signature -> {r.status_code}", r.status_code == 400,
               f"got {r.status_code}", "P3")
        # declining a mandatory form rejected
        r = c.post(f"/api/students/{sid}/waivers/{mid}/sign",
                   json={"signed_name": "Pat Alpha", "consent": False})
        record(f"Cannot decline a mandatory waiver -> {r.status_code}", r.status_code == 400,
               f"got {r.status_code}", "P2")
        # declining an opt-out form allowed
        r = c.post(f"/api/students/{sid}/waivers/{oid}/sign",
                   json={"signed_name": "Pat Alpha", "consent": False})
        record(f"Can decline an opt-out form -> {r.status_code}", r.status_code == 200,
               f"got {r.status_code}", "P2")


def run_attendance(ids):
    """Taking attendance — the most-used fall feature. Mark present persists,
    toggling again removes it (no duplicate rows), manual check-in dedups, the
    endpoints validate the student/class exist and don't 500 on a bad date, and
    parents can't mark attendance."""
    from datetime import time as _time
    from app.models import DanceClass, ClassEnrollment, Attendance
    sid = ids["child_a"]
    with app.app_context():
        admin = User.query.filter_by(username="admin").first()
        dc = DanceClass(name="Attn Class", day_of_week=0, start_time=_time(17, 0),
                        end_time=_time(18, 0), instructor_id=admin.id)
        db.session.add(dc)
        db.session.flush()
        db.session.add(ClassEnrollment(student_id=sid, class_id=dc.id))
        db.session.commit()
        cid = dc.id

    def rows():
        with app.app_context():
            return Attendance.query.filter_by(student_id=sid, class_id=cid).count()

    with app.test_client() as c:
        login(c, "admin", "admin123")
        r1 = c.post("/api/attendance/toggle", json={"student_id": sid, "class_id": cid})
        d1 = r1.get_json() or {}
        record(f"Mark present -> {r1.status_code} present={d1.get('present')}",
               r1.status_code == 201 and d1.get("present") is True, str(d1), "P1")
        r2 = c.post("/api/attendance/toggle", json={"student_id": sid, "class_id": cid})
        d2 = r2.get_json() or {}
        record(f"Toggle again removes attendance -> {r2.status_code} present={d2.get('present')}",
               r2.status_code == 200 and d2.get("present") is False and rows() == 0, str(d2), "P1")
        # Manual check-in dedups: 2nd check-in same day is rejected, leaves one row.
        c.post("/api/attendance/checkin", json={"student_id": sid, "class_id": cid})
        rc = c.post("/api/attendance/checkin", json={"student_id": sid, "class_id": cid})
        record(f"Manual check-in dedups (2nd -> {rc.status_code}, {rows()} row)",
               rc.status_code == 400 and rows() == 1, f"status={rc.status_code} rows={rows()}", "P2")
        # Validation: nonexistent class 404s (no orphan row), garbage id 400s, bad date doesn't 500.
        rb1 = c.post("/api/attendance/toggle", json={"student_id": sid, "class_id": 999999})
        rb2 = c.post("/api/attendance/toggle", json={"student_id": "xyz", "class_id": cid})
        rb3 = c.post("/api/attendance/toggle", json={"student_id": sid, "class_id": cid, "date": "not-a-date"})
        record(f"Toggle validates existence + bad date (404={rb1.status_code}, 400={rb2.status_code}, date={rb3.status_code})",
               rb1.status_code == 404 and rb2.status_code == 400 and rb3.status_code != 500,
               f"{rb1.status_code}/{rb2.status_code}/{rb3.status_code}", "P3")
        # missing fields rejected
        r3 = c.post("/api/attendance/toggle", json={"student_id": sid})
        record(f"Attendance toggle requires class_id -> {r3.status_code}", r3.status_code == 400,
               f"got {r3.status_code}", "P3")
    with app.test_client() as c:
        login(c, "parent_a", "pw")
        r = c.post("/api/attendance/toggle", json={"student_id": sid, "class_id": cid})
        record(f"Parent cannot mark attendance -> {r.status_code}", r.status_code == 403,
               f"got {r.status_code}", "P0")


def run_auto_reminders():
    """Auto-reminders email/SMS families with balances, and run on every boot +
    cron (the machine wakes/sleeps all day). They MUST fire at most once per
    month or families get spammed. Verify: disabled = no-op; enabled marks the
    month done BEFORE sending (so a mid-loop crash can't cause a re-send); and a
    repeat run in the same month is a gated no-op."""
    from datetime import date
    from app import _process_auto_reminders
    from app.models import Setting
    ym = date.today().strftime("%Y-%m")
    with app.app_context():
        # Disabled -> returns before writing the marker.
        Setting.set("reminders_auto_enabled", "0")
        Setting.set("reminders_last_run", "SENTINEL")
        _process_auto_reminders()
        record("Auto-reminders skip entirely when disabled",
               Setting.get("reminders_last_run") == "SENTINEL", "ran while disabled", "P2")
        # Enabled on today's day -> marks the month done (mark-first).
        Setting.set("reminders_auto_enabled", "1")
        Setting.set("reminders_day_of_month", str(date.today().day))
        Setting.set("reminders_last_run", "")
        _process_auto_reminders()
        record(f"Auto-reminders mark the month done (mark-first) -> {Setting.get('reminders_last_run')}",
               Setting.get("reminders_last_run") == ym, f"got {Setting.get('reminders_last_run')}", "P1")
        # Repeat same month -> gated no-op (the anti-spam guarantee), no error.
        _process_auto_reminders()
        record("Repeat run in the same month is a gated no-op",
               Setting.get("reminders_last_run") == ym, "re-ran within the month", "P1")
        Setting.set("reminders_auto_enabled", "0")  # leave disabled for other tests


def run_message_blast():
    """Message blasts: validated, resolve recipients, degrade gracefully when
    SMTP isn't configured (save + return emails), and parents can't send."""
    with app.test_client() as c:
        login(c, "admin", "admin123")
        # 'all' resolves the two seeded parent emails; SMTP not configured -> saved + emails returned
        r = c.post("/api/messages", json={"subject": "Hi", "body": "Welcome to fall!",
                                          "recipient_type": "all"})
        d = r.get_json() or {}
        ok = r.status_code == 201 and d.get("recipient_count", 0) >= 2 and "recipient_emails" in d
        record(f"Blast to 'all' resolves recipients + degrades gracefully -> {r.status_code}",
               ok, f"status {r.status_code}: {str(d)[:80]}", "P1")
        # missing subject rejected
        r = c.post("/api/messages", json={"body": "x", "recipient_type": "all"})
        record(f"Blast requires subject -> {r.status_code}", r.status_code == 400, f"got {r.status_code}", "P3")
        # non-numeric class filter -> 400 (not 500)
        r = c.post("/api/messages", json={"subject": "x", "body": "y",
                                          "recipient_type": "class", "recipient_filter": "abc"})
        record(f"Blast rejects bad class filter (no 500) -> {r.status_code}",
               r.status_code == 400, f"got {r.status_code}", "P2")
    # parent cannot send a blast (write-guard)
    with app.test_client() as c:
        login(c, "parent_a", "pw")
        r = c.post("/api/messages", json={"subject": "x", "body": "y", "recipient_type": "all"})
        record(f"Parent cannot send a blast -> {r.status_code}", r.status_code == 403,
               f"got {r.status_code}", "P0")


def run_registration_flow():
    """Public self-registration: gated when closed, validated, and admin
    approval actually creates a family + students. The key fall-enrollment path."""
    from app.models import Setting, Family, Student, Registration

    with app.app_context():
        Setting.set("registration_open", "0")
        db.session.commit()
    with app.test_client() as pub:
        r = pub.post("/api/register", json={"parent_name": "Jo", "parent_email": "jo@x.com",
                                            "students": [{"first_name": "Kid"}]})
        record(f"Registration blocked when closed -> {r.status_code}",
               r.status_code == 403, f"got {r.status_code}", "P2")

    with app.app_context():
        Setting.set("registration_open", "1")
        db.session.commit()
    with app.test_client() as pub:
        # bad email rejected
        r = pub.post("/api/register", json={"parent_name": "Jo", "parent_email": "notanemail",
                                            "students": [{"first_name": "Kid"}]})
        record(f"Registration rejects bad email -> {r.status_code}", r.status_code == 400,
               f"got {r.status_code}", "P3")
        # no students rejected
        r = pub.post("/api/register", json={"parent_name": "Jo", "parent_email": "jo@x.com", "students": []})
        record(f"Registration rejects no dancers -> {r.status_code}", r.status_code == 400,
               f"got {r.status_code}", "P3")
        # valid submission
        r = pub.post("/api/register", json={"parent_name": "Riverside Family", "parent_email": "riv@x.com",
                                            "students": [{"first_name": "Ivy", "last_name": "River"},
                                                         {"first_name": "Max"}]})
        record(f"Valid registration accepted -> {r.status_code}", r.status_code == 201,
               f"got {r.status_code}", "P1")

    with app.app_context():
        reg = Registration.query.filter_by(parent_email="riv@x.com", status="pending").first()
        fam_before = Family.query.count()
        stu_before = Student.query.count()
        rid = reg.id if reg else None
    record("Submitted registration is queued for admin", rid is not None, "not found", "P1")

    if rid:
        with app.test_client() as c:
            login(c, "admin", "admin123")
            r = c.post(f"/api/registrations/{rid}/approve")
            record(f"Admin approve creates the family -> {r.status_code}",
                   r.status_code == 200, f"got {r.status_code}: {r.get_data(as_text=True)[:80]}", "P1")
        with app.app_context():
            grew = Family.query.count() == fam_before + 1 and Student.query.count() == stu_before + 2
            record("Approval created 1 family + 2 students", grew,
                   f"fam {fam_before}->{Family.query.count()}, stu {stu_before}->{Student.query.count()}", "P1")
            # idempotent: re-approve is rejected
        with app.test_client() as c:
            login(c, "admin", "admin123")
            r = c.post(f"/api/registrations/{rid}/approve")
            record(f"Re-approve is rejected (idempotent) -> {r.status_code}",
                   r.status_code == 400, f"got {r.status_code}", "P2")

    # The public endpoint is UNAUTHENTICATED — it must never 500 on a malformed
    # payload (non-list students, non-dict elements, non-string names), must cap
    # the dancer count, and its stored XSS must survive an admin approve + render.
    import json as _json
    from app.models import Registration as _Reg
    with app.test_client() as pub:  # no login
        malformed = [
            ({"parent_name": "P", "parent_email": "p@x.com", "students": "notalist"}, 400, "students=string"),
            ({"parent_name": "P", "parent_email": "p@x.com", "students": [123]}, 400, "students=[int]"),
            ({"parent_name": "P", "parent_email": "p@x.com", "students": {"first_name": "x"}}, 400, "students=dict"),
            ({"parent_name": 123, "parent_email": "p@x.com", "students": [{"first_name": "Ok"}]}, 201, "parent_name=int"),
            ({"parent_name": "P", "parent_email": "bad", "students": [{"first_name": "Ok"}]}, 400, "bad email"),
        ]
        for body, want, label in malformed:
            r = pub.post("/api/register", json=body)
            record(f"Public register robust: {label} -> {r.status_code}",
                   r.status_code == want and r.status_code < 500, f"got {r.status_code} (want {want})", "P2")
        # Cap: 100 dancers submitted -> at most 30 stored.
        pub.post("/api/register", json={"parent_name": "Capped", "parent_email": "cap@x.com",
                                        "students": [{"first_name": f"D{i}"} for i in range(100)]})
    with app.app_context():
        capped = _Reg.query.filter_by(parent_email="cap@x.com").first()
        n = len(_json.loads(capped.students_json)) if capped else 999
        record(f"Public register caps dancer count (stored {n})", n <= 30, f"stored {n}", "P3")
    # Malformed + XSS registration approves cleanly and renders escaped-at-output.
    with app.test_client() as pub:
        pub.post("/api/register", json={
            "parent_name": "<script>x</script>", "parent_email": "xss@x.com",
            "students": [{"first_name": "<script>", "last_name": 123, "dob": "bad"}, "junk"]})
    with app.app_context():
        xreg = _Reg.query.filter_by(parent_email="xss@x.com", status="pending").first()
        xrid = xreg.id if xreg else None
    with app.test_client() as c:
        login(c, "admin", "admin123")
        ra = c.post(f"/api/registrations/{xrid}/approve") if xrid else None
        record(f"Approve of a malformed/XSS registration doesn't 500 -> {ra.status_code if ra else 'n/a'}",
               ra is not None and ra.status_code in (200, 201), f"got {ra.status_code if ra else 'n/a'}", "P2")
        record(f"Registrations + students lists render after XSS approve",
               c.get("/api/registrations?status=all").status_code == 200 and c.get("/api/students").status_code == 200,
               "a list 500'd", "P2")


def run_amount_validation(ids):
    """Financial write endpoints must reject bad amounts (negative = balance
    corruption) and bad types, and accept a valid charge."""
    sid = ids["child_a"]
    with app.test_client() as c:
        login(c, "admin", "admin123")
        bad = [
            ({"student_id": sid, "type": "charge", "amount": -50, "category": "tuition"}, "negative amount"),
            ({"student_id": sid, "type": "charge", "amount": "abc", "category": "tuition"}, "non-numeric amount"),
            ({"student_id": sid, "type": "charge", "amount": 5_000_000, "category": "tuition"}, "absurd amount"),
            ({"student_id": sid, "type": "wat", "amount": 10, "category": "tuition"}, "invalid type"),
        ]
        for body, desc in bad:
            r = c.post("/api/transactions", json=body)
            record(f"create_transaction rejects {desc} -> {r.status_code}",
                   r.status_code == 400, f"got {r.status_code} (should reject)", "P2")
        # bulk-charge negative rejected before touching any student
        r = c.post("/api/transactions/bulk-charge",
                   json={"class_id": 1, "amount": -10, "category": "tuition"})
        record(f"bulk_charge rejects negative amount -> {r.status_code}",
               r.status_code == 400, f"got {r.status_code}", "P2")
        # a valid charge still works
        r = c.post("/api/transactions",
                   json={"student_id": sid, "type": "charge", "amount": 42.50, "category": "tuition"})
        record(f"create_transaction accepts a valid charge -> {r.status_code}",
               r.status_code == 201, f"got {r.status_code}", "P1")

        # Recurring charges fire automatically every month, so a bad amount is
        # worse here than a one-off (a negative = a silent monthly credit). Must
        # be validated the same way. Needs a real class to attach to.
        with app.app_context():
            from datetime import time as _t
            from app.models import DanceClass, User as _U
            adm = _U.query.filter_by(username="admin").first()
            rcx = DanceClass(name="RC Class", day_of_week=0, start_time=_t(17, 0),
                             end_time=_t(18, 0), instructor_id=adm.id)
            db.session.add(rcx)
            db.session.commit()
            rc_cid = rcx.id
        for body, want, label in [
            ({"class_id": rc_cid, "amount": -50, "category": "tuition", "day_of_month": 1}, 400, "negative"),
            ({"class_id": rc_cid, "amount": "abc", "category": "tuition", "day_of_month": 1}, 400, "non-numeric"),
            ({"class_id": rc_cid, "amount": 9_999_999, "category": "tuition", "day_of_month": 1}, 400, "absurd"),
            ({"class_id": rc_cid, "amount": 50, "category": "tuition", "day_of_month": "xyz"}, 400, "garbage day"),
            ({"class_id": rc_cid, "amount": 75.50, "category": "tuition", "day_of_month": 15}, 201, "valid"),
        ]:
            rr = c.post("/api/recurring-charges", json=body)
            record(f"recurring_charge {label} amount/day -> {rr.status_code}",
                   rr.status_code == want and rr.status_code < 500, f"got {rr.status_code} (want {want})", "P2")


def run_transaction_delete(ids):
    """An admin must be able to correct a mistake by deleting a posted charge or
    payment, and the balance must recompute. A parent must NOT be able to delete
    a transaction (it would erase their own debt)."""
    from app.helpers import calc_balance
    sid = ids["child_a"]
    # Admin posts a distinctive charge. (Separate, non-nested clients — nesting
    # test_client() context managers bleeds the session between them.)
    with app.app_context():
        base = calc_balance(sid)["balance"]
    with app.test_client() as c:
        login(c, "admin", "admin123")
        r = c.post("/api/transactions",
                   json={"student_id": sid, "type": "charge", "amount": 123.45, "category": "tuition"})
        tid = r.get_json().get("id")
    with app.app_context():
        after_charge = calc_balance(sid)["balance"]
    record(f"charge raised balance by 123.45 ({base:.2f}->{after_charge:.2f})",
           round(after_charge - base, 2) == 123.45, f"delta={after_charge-base}", "P2")

    # Parent must NOT be able to delete a transaction (would erase their own debt).
    with app.test_client() as pc:
        login(pc, "parent_a", "pw")
        rp = pc.delete(f"/api/transactions/{tid}")
    record(f"Parent blocked from deleting a transaction -> {rp.status_code}",
           rp.status_code in (401, 403), f"got {rp.status_code}", "P0")
    with app.app_context():
        still_there = calc_balance(sid)["balance"]
    record("Parent's blocked delete did NOT change the balance",
           round(still_there - after_charge, 2) == 0.0, f"bal moved to {still_there}", "P0")

    # Admin deletes it; balance returns to baseline.
    with app.test_client() as c:
        login(c, "admin", "admin123")
        rd = c.delete(f"/api/transactions/{tid}")
        r404 = c.delete("/api/transactions/999999")
    with app.app_context():
        after_delete = calc_balance(sid)["balance"]
    record(f"Admin delete removes the charge; balance back to baseline ({after_delete:.2f})",
           rd.status_code == 200 and round(after_delete - base, 2) == 0.0,
           f"status={rd.status_code} bal={after_delete} base={base}", "P2")
    record(f"Delete of a missing transaction -> {r404.status_code}",
           r404.status_code == 404, f"got {r404.status_code}", "P3")


def run_payment_plans(ids):
    """Payment plans (a Jackrabbit-parity billing feature): generate the right
    number of installments on the right monthly schedule with the right amount,
    validate inputs, and stay admin-only. NOTE: a plan is a *schedule*, not a
    charge — toggling an installment paid does not post to the ledger; the real
    payment is recorded separately. This test guards the schedule math + authz."""
    from app.models import PaymentPlanInstallment
    sid = ids["child_a"]
    with app.test_client() as c:
        login(c, "admin", "admin123")
        r = c.post(f"/api/students/{sid}/payment-plan",
                   json={"installment_amount": 100, "num_installments": 6, "day_of_month": 15})
        record(f"Create payment plan -> {r.status_code}", r.status_code == 201, r.get_data(as_text=True)[:60], "P2")
        with app.app_context():
            insts = PaymentPlanInstallment.query.order_by(PaymentPlanInstallment.seq).all()
        good = (len(insts) == 6 and all(i.due_date.day == 15 for i in insts)
                and all(float(i.amount) == 100.0 for i in insts)
                and all(insts[k].due_date > insts[k - 1].due_date for k in range(1, len(insts))))
        record(f"Plan: 6 monthly installments of $100 on the 15th (got {len(insts)})",
               good, f"dates={[i.due_date.isoformat() for i in insts]}", "P2")
        # Validation
        rb = c.post(f"/api/students/{sid}/payment-plan",
                    json={"installment_amount": "x", "num_installments": 6, "day_of_month": 15})
        rd = c.post(f"/api/students/{sid}/payment-plan",
                    json={"installment_amount": 100, "num_installments": 6, "day_of_month": 31})
        rn = c.post("/api/students/999999/payment-plan",
                    json={"installment_amount": 100, "num_installments": 6, "day_of_month": 15})
        record(f"Plan validation: garbage={rb.status_code} day31={rd.status_code} nostudent={rn.status_code}",
               rb.status_code == 400 and rd.status_code == 400 and rn.status_code == 404,
               f"{rb.status_code}/{rd.status_code}/{rn.status_code}", "P3")
        if insts:
            t = c.post(f"/api/payment-plan-installments/{insts[0].id}/toggle-paid")
            record(f"Toggle installment paid -> {t.status_code}",
                   t.status_code == 200 and (t.get_json() or {}).get("paid") is True, "", "P3")
    with app.test_client() as c:
        login(c, "parent_a", "pw")
        rp = c.post(f"/api/students/{sid}/payment-plan",
                    json={"installment_amount": 100, "num_installments": 6, "day_of_month": 15})
        record(f"Parent cannot create a payment plan -> {rp.status_code}", rp.status_code == 403,
               f"got {rp.status_code}", "P0")


def run_input_robustness(ids):
    """No write endpoint may 500 on malformed input. An unhandled exception
    (e.g. float() on a garbage string) is bad UX for the parent AND can leave a
    DB transaction half-applied. Every endpoint must reject bad input with a
    4xx, not blow up. Fuzz each pure-DB-write endpoint with a no-body / empty /
    garbage-typed / wrong-typed / negative-huge payload and assert no 500."""
    sid = ids["child_a"]
    endpoints = [
        ("POST", "/api/classes"), ("POST", "/api/families"), ("POST", "/api/students"),
        ("POST", "/api/locations"), ("POST", "/api/leads"), ("POST", "/api/makeups"),
        ("POST", "/api/rules"), ("POST", "/api/skills"), ("POST", "/api/staff"),
        ("POST", "/api/donations"), ("POST", "/api/transactions"),
        ("POST", "/api/transactions/bulk-charge"), ("POST", "/api/recurring-charges"),
        ("POST", "/api/recitals"), ("POST", "/api/performance/groups"),
        ("POST", "/api/performance/auditions"), ("POST", "/api/performance/performances"),
        ("POST", "/api/waivers/templates"), ("PUT", "/api/settings/payments"),
        ("POST", f"/api/students/{sid}/payment-plan"),
        ("POST", "/api/balances/apply-late-fees"),
    ]
    payloads = [
        ("no-body", None),
        ("empty-dict", {}),
        ("garbage-strings", {"amount": "abc", "student_id": "xyz", "class_id": "nope",
                             "day_of_month": "soon", "name": 123, "category": None,
                             "email": [], "date": "not-a-date", "installments": "many"}),
        ("wrong-types", {"amount": [], "student_id": {}, "student_ids": "notalist",
                         "class_id": True, "day_of_month": 99, "amount_cents": -5}),
        ("negative-huge", {"amount": -999999, "student_id": -1, "class_id": 0,
                           "day_of_month": -3, "installments": -2}),
    ]
    with app.test_client() as c:
        login(c, "admin", "admin123")
        for method, path in endpoints:
            fn = getattr(c, method.lower())
            bad = []
            for label, body in payloads:
                try:
                    r = fn(path, data="", content_type="application/json") if body is None else fn(path, json=body)
                    if r.status_code == 500:
                        bad.append(f"{label}->500")
                except Exception as e:  # a raised exception is as bad as a 500
                    bad.append(f"{label}->EXC {type(e).__name__}")
            record(f"{method} {path} handles malformed input without 500",
                   not bad, f"failed: {bad}", "P2")


def run_parent_input_robustness(ids):
    """Parent-reachable writes must not 500 on a bad student_id. Staff skip the
    parent-authorization branch, so an unguarded int(student_id) only blows up
    for an actual parent — the admin sweep can't see it. Seed the target rows,
    then post malformed ids AS a parent and assert no 500 (and no orphan row)."""
    from app.models import (Rule, Audition, Performance, TicketType,
                            PerformanceGroup)
    cid = ids["child_a"]
    with app.app_context():
        grp = PerformanceGroup(name="Robustness Co")
        db.session.add(grp)
        db.session.flush()
        aud = Audition(title="Robust Audition", group_id=grp.id, is_open=True)
        rule = Rule(text="Be kind", display_order=99)
        perf = Performance(title="Robust Show", group_id=grp.id)
        db.session.add_all([aud, rule, perf])
        db.session.flush()
        tt = TicketType(performance_id=perf.id, name="GA", price=10)
        db.session.add(tt)
        db.session.commit()
        aid, rid, pid, ttid = aud.id, rule.id, perf.id, tt.id

    cases = [
        (f"/api/performance/auditions/{aid}/signup",
         [{"student_id": "xyz"}, {"student_id": -1}, {"student_id": []}, {},
          {"student_id": 99999}, {"student_id": cid, "notes": 123}]),
        (f"/api/rules/{rid}/acknowledge",
         [{"student_id": "xyz", "initials": "AB"}, {"student_id": cid, "initials": 123},
          {"student_id": -1, "initials": "AB"}, {}]),
        (f"/api/performances/{pid}/ticket-orders",
         [{"ticket_type_id": ttid, "quantity": "lots", "student_id": cid},
          {"ticket_type_id": ttid, "student_id": "xyz"},
          {"ticket_type_id": ttid, "student_id": -1}]),
    ]
    with app.test_client() as c:
        login(c, "parent_a", "pw")
        for path, payloads in cases:
            bad = []
            for body in payloads:
                try:
                    r = c.post(path, json=body)
                    if r.status_code == 500:
                        bad.append(f"{body}->500")
                except Exception as e:
                    bad.append(f"{body}->EXC {type(e).__name__}")
            record(f"parent POST {path} handles bad student_id without 500",
                   not bad, f"failed: {bad}", "P2")


def run_parent_write_authz(ids):
    """Object-level authorization on the parent-ALLOWED writes: a parent may
    write (claim payment, sign waiver, acknowledge rule, request makeup, audition
    signup, ticket order) — but ONLY against their own child. Acting on another
    family's child must be blocked (403/404). This is the IDOR-in-writes companion
    to run_idor's read sweep. Attacker = parent_b, target = parent_a's child_a."""
    from app.models import (WaiverTemplate, Rule, Audition, Performance,
                            TicketType, PerformanceGroup)
    victim = ids["child_a"]      # parent_a's child
    victim_fam = ids["fam_a"]
    with app.app_context():
        grp = PerformanceGroup(name="Authz Co")
        db.session.add(grp)
        db.session.flush()
        wt = WaiverTemplate(title="Authz Waiver", body="...", allow_decline=True)
        rule = Rule(text="Authz rule", display_order=98)
        aud = Audition(title="Authz Aud", group_id=grp.id, is_open=True)
        perf = Performance(title="Authz Show", group_id=grp.id)
        db.session.add_all([wt, rule, aud, perf])
        db.session.flush()
        tt = TicketType(performance_id=perf.id, name="GA", price=10)
        db.session.add(tt)
        db.session.commit()
        wtid, rid, aid, pid, ttid = wt.id, rule.id, aud.id, perf.id, tt.id

    attacks = [
        ("POST", "/api/payments/claim",
         {"method": "zelle", "amount": 50, "student_id": victim}, "claim payment for another child"),
        ("POST", "/api/payments/claim",
         {"method": "zelle", "amount": 50, "family_id": victim_fam}, "claim payment for another family"),
        ("POST", f"/api/students/{victim}/waivers/{wtid}/sign",
         {"signed_name": "Attacker", "consent": True}, "sign waiver for another child"),
        ("POST", f"/api/rules/{rid}/acknowledge",
         {"student_id": victim, "initials": "XX"}, "acknowledge rule for another child"),
        ("POST", "/api/makeups",
         {"student_id": victim, "missed_date": "2026-07-01"}, "request makeup for another child"),
        ("POST", f"/api/performance/auditions/{aid}/signup",
         {"student_id": victim}, "audition signup for another child"),
        ("POST", f"/api/performances/{pid}/ticket-orders",
         {"ticket_type_id": ttid, "student_id": victim}, "ticket order for another child"),
    ]
    with app.test_client() as c:
        login(c, "parent_b", "pw")
        for method, path, body, desc in attacks:
            r = c.open(path, method=method, json=body)
            blocked = r.status_code in (401, 403, 404)
            record(f"IDOR-write blocked: {desc} [{path}] -> {r.status_code}",
                   blocked, f"got {r.status_code}, expected 403/404", "P0")
        # claim_payment must not 500 on a garbage id (parent-reachable).
        for bad in ({"method": "zelle", "amount": 50, "student_id": "xyz"},
                    {"method": "zelle", "amount": 50, "family_id": "xyz"}):
            r = c.post("/api/payments/claim", json=bad)
            record(f"claim_payment handles bad id without 500 -> {r.status_code}",
                   r.status_code != 500, f"got {r.status_code}", "P2")


def run_backup(ids):
    """Admin can download a complete, valid SQLite backup; non-admins can't.
    This is the studio's disaster-recovery net, so the file must be a real,
    openable SQLite snapshot that actually contains the data — and it holds ALL
    families' PII + finances, so it must be admin-only (a parent gets 403)."""
    import sqlite3
    # Admin: 200, valid SQLite, contains the seeded students.
    with app.test_client() as c:
        login(c, "admin", "admin123")
        r = c.get("/api/admin/backup")
        magic = r.data[:16] == b"SQLite format 3\x00"
        record(f"Admin downloads a backup -> {r.status_code}, {len(r.data)} bytes",
               r.status_code == 200 and magic, f"status={r.status_code} magic={magic}", "P2")
        if r.status_code == 200 and magic:
            bt = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            bt.write(r.data)
            bt.close()
            try:
                con = sqlite3.connect(bt.name)
                n = con.execute("SELECT COUNT(*) FROM students").fetchone()[0]
                con.close()
                record(f"Backup is a valid DB containing the data ({n} students)",
                       n >= 2, f"students in backup: {n}", "P2")
            finally:
                try:
                    os.unlink(bt.name)
                except OSError:
                    pass
    # Parent: blocked (the backup holds every family's PII + finances).
    with app.test_client() as c:
        login(c, "parent_a", "pw")
        r = c.get("/api/admin/backup")
        record(f"Parent blocked from full DB backup -> {r.status_code}",
               r.status_code in (401, 403), f"got {r.status_code}", "P0")


def run_orphan_render_guard(ids):
    """Belt-and-suspenders for the whole dead-page bug class: even if an orphan
    row exists (e.g. left in prod by the old buggy create endpoints, before they
    were fixed), the roster serializers must null-guard the relationship so the
    list still renders instead of 500-ing. Inject orphan rows directly (bypassing
    the now-fixed endpoints) and assert every affected list GET returns 200."""
    from datetime import time as _time
    from app.models import (MakeupClass, WaitlistEntry, CompanyMembership,
                            PerformanceGroup, Attendance, Transaction, DanceClass)
    GHOST = 987654  # a student id that does not exist
    with app.app_context():
        admin = User.query.filter_by(username="admin").first()
        g = PerformanceGroup(name="Ghost Co")
        db.session.add(g)
        db.session.flush()
        dc = DanceClass(name="Ghost Class", day_of_week=0, start_time=_time(17, 0),
                        end_time=_time(18, 0), instructor_id=admin.id)
        db.session.add(dc)
        db.session.flush()
        db.session.add_all([
            MakeupClass(student_id=GHOST, status='requested'),
            WaitlistEntry(class_id=dc.id, student_id=GHOST, status='waiting'),
            CompanyMembership(group_id=g.id, student_id=GHOST),
            Attendance(student_id=GHOST, class_id=dc.id),
            Transaction(student_id=GHOST, type='charge', amount=10, category='tuition',
                        payment_method='n/a', description='ghost'),
        ])
        db.session.commit()
        gid, cid = g.id, dc.id

    with app.test_client() as c:
        login(c, "admin", "admin123")
        for label, url in [
            ("makeups", "/api/makeups"),
            ("waitlist", f"/api/classes/{cid}/waitlist"),
            ("group members", f"/api/performance/groups/{gid}/members"),
            ("attendance", "/api/attendance"),
            ("transactions", "/api/transactions"),
        ]:
            r = c.get(url)
            record(f"Roster renders with an orphan row: {label} -> {r.status_code}",
                   r.status_code == 200, f"got {r.status_code} (dead-page on orphan data)", "P2")


def run_class_render_guard(ids):
    """The class list is a core, high-traffic page. A class whose instructor is
    missing (a bad instructor_id at create, or a user removed later) must not
    500 it — class_to_dict has to null-guard the instructor the way it already
    guards the location. Also: create_class must reject a bad instructor/location
    reference up front (400/404) rather than 500 or orphan."""
    from datetime import time as _time
    from app.models import DanceClass
    base = {"name": "Guard", "day_of_week": 0, "start_time": "17:00", "end_time": "18:00"}
    with app.test_client() as c:
        login(c, "admin", "admin123")
        r1 = c.post("/api/classes", json={**base, "instructor_id": "xyz"})
        record(f"create_class rejects garbage instructor_id -> {r1.status_code}",
               r1.status_code == 400, f"got {r1.status_code}", "P3")
        r2 = c.post("/api/classes", json={**base, "instructor_id": 999999})
        record(f"create_class rejects nonexistent instructor -> {r2.status_code}",
               r2.status_code == 404, f"got {r2.status_code}", "P2")
        r3 = c.post("/api/classes", json={**base, "location_id": 999999})
        record(f"create_class rejects nonexistent location -> {r3.status_code}",
               r3.status_code == 404, f"got {r3.status_code}", "P3")
    # Simulate a class whose instructor row is gone (bypass the endpoint), then
    # confirm the class list still renders (the serializer null-guard).
    with app.app_context():
        dc = DanceClass(name="Orphan Instr", day_of_week=0, start_time=_time(17, 0),
                        end_time=_time(18, 0), instructor_id=999999)
        db.session.add(dc)
        db.session.commit()
    with app.test_client() as c:
        login(c, "admin", "admin123")
        rl = c.get("/api/classes")
        record(f"Class list renders with a missing-instructor class -> {rl.status_code}",
               rl.status_code == 200, f"got {rl.status_code} (dead-page regression)", "P2")


def run_orphan_guard(ids):
    """Systematic guard against the recurring orphan-row bug: a create endpoint
    that stores a request-supplied student_id without checking it exists will
    orphan a row that then 500s its roster page (hit repeatedly: makeups,
    attendance, waitlist, and the whole performance/recital assign surface).
    Every such endpoint must reject a nonexistent id (404), reject garbage (400),
    and leave its roster page rendering (200)."""
    from app.models import (PerformanceGroup, Performance, Costume, Recital,
                            RecitalNumber)
    with app.app_context():
        g = PerformanceGroup(name="Orphan Co")
        db.session.add(g)
        db.session.flush()
        p = Performance(title="Orphan Show", group_id=g.id)
        cst = Costume(name="Orphan Tutu")
        rec = Recital(year=2027, title="Orphan Recital")
        db.session.add_all([p, cst, rec])
        db.session.flush()
        num = RecitalNumber(recital_id=rec.id, title="Opening", order_index=1)
        db.session.add(num)
        db.session.commit()
        gid, pid, cid, rid, nid = g.id, p.id, cst.id, rec.id, num.id

    # (label, create-url, roster-GET-url, extra required fields)
    cases = [
        ("group member", f"/api/performance/groups/{gid}/members", f"/api/performance/groups/{gid}/members", {}),
        ("perf assignment", f"/api/performance/performances/{pid}/assignments", f"/api/performance/performances/{pid}/assignments", {}),
        ("costume assign", f"/api/costumes/{cid}/assignments", f"/api/costumes/{cid}/assignments", {}),
        ("recital cast", f"/api/recital-numbers/{nid}/cast", f"/api/recital-numbers/{nid}/cast", {}),
        ("recital award", f"/api/recitals/{rid}/awards", f"/api/recitals/{rid}/awards", {"title": "Best"}),
        ("recital ad", f"/api/recitals/{rid}/ads", f"/api/recitals/{rid}/ads", {"advertiser": "ACME"}),
    ]
    with app.test_client() as c:
        login(c, "admin", "admin123")
        for label, post_url, list_url, extra in cases:
            rn = c.post(post_url, json={"student_id": 999999, **extra})
            rg = c.post(post_url, json={"student_id": "xyz", **extra})
            rl = c.get(list_url)
            ok = rn.status_code == 404 and rg.status_code == 400 and rl.status_code == 200
            record(f"orphan-guard {label}: nonexistent->{rn.status_code} garbage->{rg.status_code} roster->{rl.status_code}",
                   ok, f"{rn.status_code}/{rg.status_code}/{rl.status_code} (want 404/400/200)", "P2")


def run_csv_exports(ids):
    """CSV exports: staff get a well-formed CSV; parents are blocked."""
    # Parent blocked.
    with app.test_client() as c:
        login(c, "parent_a", "pw")
        for path in ("/api/reports/students.csv", "/api/reports/transactions.csv"):
            r = c.get(path)
            record(f"Parent blocked from {path} -> {r.status_code}",
                   r.status_code in (401, 403), f"got {r.status_code}", "P0")
    # Admin gets CSV with header + the seeded students.
    with app.test_client() as c:
        login(c, "admin", "admin123")
        r = c.get("/api/reports/students.csv")
        ct = r.headers.get("Content-Type", "")
        body = r.get_data(as_text=True)
        ok = r.status_code == 200 and "text/csv" in ct and body.startswith("Last name,First name")
        record(f"Students CSV export well-formed -> {r.status_code}, ct={ct.split(';')[0]}",
               ok, f"status={r.status_code} ct={ct} head={body[:40]!r}", "P2")
        has_dispo = "attachment" in r.headers.get("Content-Disposition", "")
        record("Students CSV has attachment disposition", has_dispo,
               r.headers.get("Content-Disposition", "<none>"), "P3")
        r2 = c.get("/api/reports/transactions.csv")
        record(f"Transactions CSV export well-formed -> {r2.status_code}",
               r2.status_code == 200 and r2.get_data(as_text=True).startswith("Date,Student"),
               f"head={r2.get_data(as_text=True)[:40]!r}", "P2")
        rev = c.get("/api/reports/revenue").get_json()
        ok = (rev and isinstance(rev.get("monthly"), list) and len(rev["monthly"]) == 12
              and "totals" in rev and "collected_this_year" in rev["totals"])
        record("Revenue report returns 12 months + totals", ok, str(rev)[:80], "P2")


def run_xss_guard():
    """Static guard: user-controlled name/text fields must never be interpolated
    into a JS template literal without esc(). These fields come from public
    self-registration, so an unescaped one is stored XSS into a staff/admin view."""
    import re
    from pathlib import Path

    # Fields that hold user-controlled free text (excludes server enums like
    # `status`, ids, dates, and numeric fields, which aren't injectable).
    FIELDS = ("student_name", "family_name", "donor_name", "parent_name",
              "full_name", "instructor_name", "group_name", "costume_name",
              "song_title", "song_artist", "choreographer", "note", "notes",
              "description", "body", "title", "reference", "memo", "venue",
              "location_text", "admin_note", "allergies", "special_needs",
              "interest", "source", "props", "message", "subject")
    tdir = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "app" / "templates"
    offenders = []
    for f in tdir.rglob("*.html"):
        for m in re.finditer(r"\$\{\s*([A-Za-z_]\w*)\.(" + "|".join(FIELDS) + r")\s*\}", f.read_text()):
            # `${x.student_name}` with no esc() around it
            offenders.append(f"{f.relative_to(tdir)}: ${{{m.group(1)}.{m.group(2)}}}")
    record(f"No user-name field rendered without esc() ({len(offenders)} found)",
           not offenders, "; ".join(offenders[:8]), "P1")


def run_js_syntax():
    """Node-check the inline <script> of JS-heavy pages. A rendered-JS syntax
    error (e.g. a bad string escape) silently kills a whole page's behavior and
    is invisible to Jinja compile/render checks — this catches that class."""
    import re
    import shutil
    import subprocess
    import tempfile as _tf

    node = shutil.which("node")
    if not node:
        record("JS syntax check (node not found — skipped)", True, "", "P3")
        return

    pages = [("admin", "admin123", ["/dashboard", "/reports/aging"]),
             ("parent_a", "pw", ["/parent"])]
    bad = []
    for user, pw, paths in pages:
        with app.test_client() as c:
            login(c, user, pw)
            for path in paths:
                html = c.get(path).get_data(as_text=True)
                for i, script in enumerate(re.findall(r"<script>(.*?)</script>", html, re.S)):
                    if "function" not in script and "=>" not in script:
                        continue
                    f = _tf.NamedTemporaryFile("w", suffix=".js", delete=False)
                    f.write(script)
                    f.close()
                    r = subprocess.run([node, "--check", f.name], capture_output=True, text=True)
                    os.unlink(f.name)
                    if r.returncode != 0:
                        first = (r.stderr.strip().splitlines() or ["?"])[-3:]
                        bad.append(f"{path}#script{i}: {' '.join(first)[:120]}")
    record(f"Rendered inline JS parses on {sum(len(p[2]) for p in pages)} JS-heavy pages",
           not bad, "; ".join(bad), "P1")


def run_smoke():
    """As admin, GET every no-arg GET route; assert no 500s."""
    with app.test_client() as c:
        login(c, "admin", "admin123")
        with app.app_context():
            rules = [r for r in app.url_map.iter_rules()
                     if "GET" in r.methods and not r.arguments
                     and not r.rule.startswith("/static")
                     and "logout" not in r.rule]
        errors = []
        for r in sorted(rules, key=lambda x: x.rule):
            try:
                resp = c.get(r.rule)
                if resp.status_code >= 500:
                    errors.append(f"{r.rule} -> {resp.status_code}")
            except Exception as e:  # noqa: BLE001
                errors.append(f"{r.rule} -> EXC {type(e).__name__}: {e}")
        record(f"Admin no-arg GET smoke ({len(rules)} routes, {len(errors)} failing)",
               not errors, "; ".join(errors[:15]), "P1")


def run_empty_state():
    """Day-one check: a fresh studio (only the auto-seeded admin, NO families /
    classes / transactions / recitals) must render every page and no-arg API GET
    without a 500. Aggregation pages (analytics, reports, giving statement) are
    the usual empty-data landmines (division by zero, empty-list indexing). Runs
    in a subprocess against a throwaway DB because this suite's own app is already
    seeded with two families."""
    import subprocess
    snippet = (
        "import os, json\n"
        "from app import create_app\n"
        "app = create_app('development'); app.config['TESTING'] = True\n"
        "with app.app_context():\n"
        "    rules = sorted({r.rule for r in app.url_map.iter_rules()\n"
        "        if 'GET' in r.methods and not r.arguments\n"
        "        and not r.rule.startswith('/static') and 'logout' not in r.rule})\n"
        "bad = []\n"
        "with app.test_client() as c:\n"
        "    c.post('/auth/login', data={'username':'admin','password':'admin123'}, follow_redirects=True)\n"
        "    for path in rules:\n"
        "        try:\n"
        "            if c.get(path).status_code >= 500: bad.append(path)\n"
        "        except Exception as e:\n"
        "            bad.append(f'{path}!{type(e).__name__}')\n"
        "print(json.dumps({'n': len(rules), 'bad': bad}))\n"
    )
    env = dict(os.environ)
    env["RFID_ENABLED"] = "false"
    env["DATABASE_URL"] = f"sqlite:///{tempfile.NamedTemporaryFile(suffix='.db').name}"
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        p = subprocess.run([sys.executable, "-c", snippet], capture_output=True,
                           text=True, cwd=root, env=env, timeout=120)
        import json as _json
        out = _json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {"n": 0, "bad": ["no output"]}
        bad = out["bad"]
        record(f"Fresh empty studio renders cleanly ({out['n']} routes, {len(bad)} failing)",
               not bad, f"5xx on empty data: {bad[:15]}", "P1")
    except Exception as e:  # noqa: BLE001
        record("Fresh empty studio renders cleanly", False, f"probe failed: {e}", "P1")


def main():
    ids = seed()
    run_idor(ids)
    run_csrf()
    run_waiver_signing(ids)
    run_attendance(ids)
    run_message_blast()
    run_auto_reminders()
    run_multichild_invite_merge()
    run_square_webhook(ids)
    run_reconciliation(ids)
    run_enrollment(ids)
    run_deactivation_revokes_session()
    run_password_reset()
    run_login_by_email()
    run_registration_flow()
    run_amount_validation(ids)
    run_payment_plans(ids)
    run_transaction_delete(ids)
    run_input_robustness(ids)
    run_parent_input_robustness(ids)
    run_parent_write_authz(ids)
    run_class_render_guard(ids)
    run_orphan_guard(ids)
    run_orphan_render_guard(ids)
    run_prod_security_config()
    run_backup(ids)
    run_csv_exports(ids)
    run_xss_guard()
    run_js_syntax()
    run_smoke()
    run_empty_state()

    fails = [r for r in results if not r[2]]
    p0 = [r for r in fails if r[0] == "P0"]
    print("\n" + "=" * 60)
    print(f"SUMMARY: {len(results) - len(fails)}/{len(results)} passed, "
          f"{len(fails)} failed ({len(p0)} P0).")
    try:
        os.unlink(_tmp.name)
    except OSError:
        pass
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
