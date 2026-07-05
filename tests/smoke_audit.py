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
                          allergies="peanuts", special_needs="asthma")
        child_b = Student(first_name="Bo", last_name="Beta", family_id=fam_b.id,
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
