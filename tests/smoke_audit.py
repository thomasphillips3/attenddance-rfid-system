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
            ("GET",    f"/api/students/{bid}/payment-plan",    "read other child's plan"),
            ("GET",    f"/api/families/{fbid}/ledger",         "read other family's ledger"),
        ]
        for method, path, desc in probes:
            resp = c.open(path, method=method, json={} if method != "GET" else None)
            blocked = resp.status_code in (401, 403, 404)
            record(f"IDOR blocked: {desc} [{method} {path}] -> {resp.status_code}",
                   blocked, f"got {resp.status_code}, expected 401/403/404", "P0")

        # Parent must not reach staff-only endpoints (reads).
        staff_only = [
            ("GET", "/api/students"),          # full roster
            ("GET", "/api/transactions"),      # all money
            ("GET", "/api/users"),             # all accounts
            ("GET", "/api/families"),          # all families
            ("GET", "/api/messages"),          # all sent messages
            ("GET", "/api/balances"),          # every family's balance
            ("GET", "/api/attendance/today"),  # attendance
            ("GET", "/api/dashboard/stats"),   # studio stats
            ("GET", "/api/reports/aging"),     # A/R aging report
            ("GET", "/api/reports/revenue"),   # revenue report
        ]
        for method, path in staff_only:
            resp = c.open(path, method=method)
            blocked = resp.status_code in (401, 403, 404)
            record(f"Parent blocked from staff read [{method} {path}] -> {resp.status_code}",
                   blocked, f"got {resp.status_code}", "P0")

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
    """Taking attendance — the most-used fall feature: mark present persists,
    toggling again removes it, and parents can't mark attendance."""
    sid = ids["child_a"]
    with app.test_client() as c:
        login(c, "admin", "admin123")
        r1 = c.post("/api/attendance/toggle", json={"student_id": sid, "class_id": 4321})
        d1 = r1.get_json() or {}
        record(f"Mark present -> {r1.status_code} present={d1.get('present')}",
               r1.status_code == 201 and d1.get("present") is True, str(d1), "P1")
        r2 = c.post("/api/attendance/toggle", json={"student_id": sid, "class_id": 4321})
        d2 = r2.get_json() or {}
        record(f"Toggle again removes attendance -> {r2.status_code} present={d2.get('present')}",
               r2.status_code == 200 and d2.get("present") is False, str(d2), "P1")
        # missing fields rejected
        r3 = c.post("/api/attendance/toggle", json={"student_id": sid})
        record(f"Attendance toggle requires class_id -> {r3.status_code}", r3.status_code == 400,
               f"got {r3.status_code}", "P3")
    with app.test_client() as c:
        login(c, "parent_a", "pw")
        r = c.post("/api/attendance/toggle", json={"student_id": sid, "class_id": 4321})
        record(f"Parent cannot mark attendance -> {r.status_code}", r.status_code == 403,
               f"got {r.status_code}", "P0")


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


def main():
    ids = seed()
    run_idor(ids)
    run_csrf()
    run_waiver_signing(ids)
    run_attendance(ids)
    run_message_blast()
    run_multichild_invite_merge()
    run_reconciliation(ids)
    run_enrollment(ids)
    run_deactivation_revokes_session()
    run_password_reset()
    run_login_by_email()
    run_registration_flow()
    run_amount_validation(ids)
    run_csv_exports(ids)
    run_xss_guard()
    run_js_syntax()
    run_smoke()

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
