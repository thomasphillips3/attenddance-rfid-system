"""Billing correctness tests for AttenDANCE.

  1. allocate_family_payment never loses or invents pennies (sum == payment),
     caps each child at their balance, and credits overpayment.
  2. apply-late-fees is idempotent within a calendar month (no double-charge on
     a re-POST / double-click).

Run:  RFID_ENABLED=false python3 tests/test_billing.py
Exit 0 = all green, 1 = failures.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("RFID_ENABLED", "false")
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"

from datetime import date, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from app import create_app, db  # noqa: E402
from app.models import User, Student, Family, Transaction  # noqa: E402
from app.helpers import allocate_family_payment, calc_balance, build_aging  # noqa: E402

app = create_app("development")
app.config["TESTING"] = True

results = []


def record(name, passed, detail=""):
    results.append((name, passed))
    print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail and not passed else ""))


def seed():
    with app.app_context():
        fam = Family(name="Test Family")
        db.session.add(fam)
        db.session.flush()
        a = Student(first_name="A", last_name="T", family_id=fam.id)
        b = Student(first_name="B", last_name="T", family_id=fam.id)
        db.session.add_all([a, b])
        db.session.flush()
        # A owes 200, B owes 50
        db.session.add_all([
            Transaction(student_id=a.id, type="charge", amount=200, category="tuition",
                        payment_method="n/a", description="c"),
            Transaction(student_id=b.id, type="charge", amount=50, category="tuition",
                        payment_method="n/a", description="c"),
        ])
        admin = User(username="admin2", email="a2@x.com", first_name="Ad", last_name="Min",
                     role="admin", is_admin=True, is_active=True)
        admin.set_password("pw")
        db.session.add(admin)
        db.session.commit()
        return {"a": a.id, "b": b.id, "fam": fam.id}


def test_allocation(ids):
    with app.app_context():
        sids = [ids["a"], ids["b"]]
        # Exact, partial, over, and odd-cent amounts — sum must always equal input.
        for pay in [250.0, 100.0, 300.0, 33.33, 0.01, 175.50]:
            allocs = allocate_family_payment(sids, pay)
            total = round(sum(a for _, a in allocs), 2)
            record(f"allocation sum exact for ${pay:.2f} (got ${total:.2f})",
                   total == round(pay, 2), f"sum {total} != {pay}")
        # Each child capped at its balance for a partial payment (A=200,B=50; pay 100).
        allocs = dict(allocate_family_payment(sids, 100.0))
        record("largest-balance-first: A gets the $100 partial",
               allocs.get(ids["a"], 0) == 100.0 and ids["b"] not in allocs,
               f"{allocs}")
        # Overpayment (pay 300 vs 250 owed) fully accounted, leftover credited.
        allocs = allocate_family_payment(sids, 300.0)
        record("overpayment $300 vs $250 owed fully allocated",
               round(sum(a for _, a in allocs), 2) == 300.0, f"{allocs}")


def test_late_fee_idempotent(ids):
    with app.test_client() as c:
        c.post("/auth/login", data={"username": "admin2", "password": "pw"}, follow_redirects=True)
        body = {"amount": 15, "min_balance": 0}
        r1 = c.post("/api/balances/apply-late-fees", json=body).get_json()
        r2 = c.post("/api/balances/apply-late-fees", json=body).get_json()
        record(f"first late-fee run applies to owing students (count={r1.get('count')})",
               r1.get("count", 0) >= 1, str(r1))
        record(f"second late-fee run applies to 0, skips the rest (count={r2.get('count')}, skipped={r2.get('skipped')})",
               r2.get("count") == 0 and r2.get("skipped", 0) >= 1, str(r2))
        # Confirm the DB really has exactly one late fee per over-threshold student.
        with app.app_context():
            n = Transaction.query.filter_by(student_id=ids["a"], category="late fee").count()
            record(f"student A has exactly ONE late fee after two runs (got {n})", n == 1, f"count={n}")


def _txn(kind, amount, days_ago):
    d = date.today() - timedelta(days=days_ago)
    return SimpleNamespace(type=kind, amount=amount, transaction_date=d, created_at=None)


def test_aging():
    # Single old charge -> all in 90+.
    ag = build_aging([_txn("charge", 100, 100)])
    record("aging: 100-day charge lands in d90_plus",
           ag["d90_plus"] == 100.0 and ag["total"] == 100.0, str(ag))

    # FIFO: payment pays the OLDEST charge first.
    ag = build_aging([_txn("charge", 100, 100), _txn("charge", 50, 10), _txn("payment", 100, 5)])
    record("aging: FIFO payment clears oldest, only recent charge remains",
           ag["d90_plus"] == 0.0 and ag["current"] == 50.0 and ag["total"] == 50.0, str(ag))

    # Partial payment leaves aged remainder.
    ag = build_aging([_txn("charge", 200, 100), _txn("payment", 50, 5)])
    record("aging: partial payment leaves $150 in d90_plus",
           ag["d90_plus"] == 150.0 and ag["total"] == 150.0, str(ag))

    # Overpayment / credit -> nothing owed.
    ag = build_aging([_txn("charge", 50, 45), _txn("payment", 80, 1)])
    record("aging: overpaid entity owes 0", ag["total"] == 0.0, str(ag))

    # Bucket boundaries: 45-day charge -> d31_60.
    ag = build_aging([_txn("charge", 75, 45)])
    record("aging: 45-day charge lands in d31_60",
           ag["d31_60"] == 75.0 and ag["total"] == 75.0, str(ag))


def test_money_precision():
    """Summing many cent-level transactions must not drift (guards against a
    future switch away from Numeric columns, or float creeping into the sums)."""
    from decimal import Decimal
    with app.app_context():
        s = Student(first_name="Cent", last_name="Precision")
        db.session.add(s)
        db.session.flush()
        for _ in range(100):
            db.session.add(Transaction(student_id=s.id, type="charge", amount="10.01",
                                       category="tuition", payment_method="n/a", description="c"))
        for _ in range(50):
            db.session.add(Transaction(student_id=s.id, type="payment", amount="3.33",
                                       category="tuition", payment_method="cash", description="p"))
        db.session.commit()
        exact = float(Decimal("10.01") * 100 - Decimal("3.33") * 50)  # 834.50
        b = calc_balance(s.id)
        record(f"balance of 100x$10.01 - 50x$3.33 == ${exact:.2f} (got ${b['balance']:.2f})",
               round(b["balance"], 2) == exact, f"{b['balance']} != {exact}")


def main():
    ids = seed()
    test_allocation(ids)
    test_late_fee_idempotent(ids)
    test_aging()
    test_money_precision()
    fails = [r for r in results if not r[1]]
    print("\n" + "=" * 56)
    print(f"SUMMARY: {len(results) - len(fails)}/{len(results)} passed, {len(fails)} failed.")
    try:
        os.unlink(_tmp.name)
    except OSError:
        pass
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
