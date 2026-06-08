"""Shared helpers for AttenDANCE — balance calculation, ledger building, serialization."""

from sqlalchemy import func
from app import db
from app.models import Transaction


def calc_balance(student_id: int) -> dict:
    """Calculate charges, payments, and balance for a student using SQL aggregation.

    Returns dict with keys: total_charges, total_payments, balance (all float).
    """
    rows = (
        db.session.query(
            Transaction.type,
            func.sum(Transaction.amount),
        )
        .filter_by(student_id=student_id)
        .group_by(Transaction.type)
        .all()
    )
    totals = {r[0]: float(r[1]) for r in rows}
    charges = totals.get('charge', 0.0)
    payments = totals.get('payment', 0.0)
    return {
        'total_charges': charges,
        'total_payments': payments,
        'balance': charges - payments,
    }


def calc_balance_bulk(student_ids: list[int]) -> dict[int, dict]:
    """Calculate balances for multiple students in one query.

    Returns {student_id: {total_charges, total_payments, balance}}.
    """
    if not student_ids:
        return {}
    rows = (
        db.session.query(
            Transaction.student_id,
            Transaction.type,
            func.sum(Transaction.amount),
        )
        .filter(Transaction.student_id.in_(student_ids))
        .group_by(Transaction.student_id, Transaction.type)
        .all()
    )
    result: dict[int, dict] = {}
    for sid, txn_type, total in rows:
        if sid not in result:
            result[sid] = {'total_charges': 0.0, 'total_payments': 0.0, 'balance': 0.0}
        if txn_type == 'charge':
            result[sid]['total_charges'] = float(total)
        else:
            result[sid]['total_payments'] = float(total)
    for sid in result:
        result[sid]['balance'] = result[sid]['total_charges'] - result[sid]['total_payments']
    # Fill in students with no transactions
    for sid in student_ids:
        if sid not in result:
            result[sid] = {'total_charges': 0.0, 'total_payments': 0.0, 'balance': 0.0}
    return result


def build_ledger(txns: list) -> dict:
    """Build a running-balance ledger from a list of Transaction objects.

    Expects txns already sorted by (transaction_date, created_at).
    Returns dict with keys: ledger (list), total_charges, total_payments, balance, by_category.
    """
    running = 0.0
    ledger = []
    total_charges = 0.0
    total_payments = 0.0
    cat_totals: dict[str, dict] = {}

    for t in txns:
        amt = float(t.amount)
        is_charge = t.type == 'charge'
        if is_charge:
            running += amt
            total_charges += amt
        else:
            running -= amt
            total_payments += amt

        # Per-category tracking
        cat = t.category
        if cat not in cat_totals:
            cat_totals[cat] = {'charges': 0.0, 'payments': 0.0}
        if is_charge:
            cat_totals[cat]['charges'] += amt
        else:
            cat_totals[cat]['payments'] += amt

        ledger.append({
            **transaction_to_dict(t),
            'running_balance': f'{running:.2f}',
        })

    by_category = {}
    for cat in sorted(cat_totals):
        c = cat_totals[cat]['charges']
        p = cat_totals[cat]['payments']
        by_category[cat] = {
            'charges': f'{c:.2f}',
            'payments': f'{p:.2f}',
            'balance': f'{c - p:.2f}',
        }

    return {
        'ledger': ledger,
        'total_charges': f'{total_charges:.2f}',
        'total_payments': f'{total_payments:.2f}',
        'balance': f'{total_charges - total_payments:.2f}',
        'by_category': by_category,
    }


def allocate_family_payment(student_ids: list[int], amount: float) -> list[tuple[int, float]]:
    """Split a lump family payment across children by outstanding balance.

    Children with the largest balances are paid down first; each is capped at
    its own balance. Any leftover (an overpayment) is appended to the first
    student as a credit so the full amount is always accounted for.

    Returns a list of (student_id, amount) tuples, amounts rounded to cents.
    """
    if not student_ids or amount <= 0:
        return []

    balances = calc_balance_bulk(student_ids)
    # Order by balance descending; only those who actually owe
    owing = sorted(
        ((sid, balances[sid]['balance']) for sid in student_ids if balances[sid]['balance'] > 0),
        key=lambda x: x[1], reverse=True,
    )

    remaining = round(amount, 2)
    allocations: list[tuple[int, float]] = []
    for sid, bal in owing:
        if remaining <= 0:
            break
        portion = round(min(bal, remaining), 2)
        if portion <= 0:
            continue
        allocations.append((sid, portion))
        remaining = round(remaining - portion, 2)

    # Leftover overpayment (or nobody owed) → credit the first student
    if remaining > 0:
        target = allocations[0][0] if allocations else student_ids[0]
        # Merge into existing allocation if present
        for i, (sid, amt) in enumerate(allocations):
            if sid == target:
                allocations[i] = (sid, round(amt + remaining, 2))
                break
        else:
            allocations.append((target, remaining))

    return allocations


# --- Serializers ---

def student_to_dict(student) -> dict:
    return {
        'id': student.id,
        'first_name': student.first_name,
        'last_name': student.last_name,
        'full_name': student.full_name,
        'email': student.email,
        'phone': student.phone,
        'date_of_birth': student.date_of_birth.isoformat() if student.date_of_birth else None,
        'age': student.age,
        'emergency_contact_name': student.emergency_contact_name,
        'emergency_contact_phone': student.emergency_contact_phone,
        'parent_email': student.parent_email,
        'school': student.school,
        'grade': student.grade,
        'allergies': student.allergies,
        'special_needs': student.special_needs,
        'height': student.height,
        'weight': student.weight,
        'shoe_size': student.shoe_size,
        'shirt_size': student.shirt_size,
        'pants_size': student.pants_size,
        'leotard_size': student.leotard_size,
        'dress_size': student.dress_size,
        'waist': student.waist,
        'girth': student.girth,
        'inseam': student.inseam,
        'neck': student.neck,
        'tight_size': student.tight_size,
        'bust': student.bust,
        'hips': student.hips,
        'sleeve': student.sleeve,
        'chest': student.chest,
        'size_notes': student.size_notes,
        'family_id': student.family_id,
        'family_name': student.family.name if student.family else None,
        'rfid_uid': student.rfid_uid,
        'has_rfid': student.has_rfid(),
        'rfid_assigned_at': student.rfid_assigned_at.isoformat() if student.rfid_assigned_at else None,
        'is_active': student.is_active,
        'enrollment_date': student.enrollment_date.isoformat(),
        'notes': student.notes,
        'medical_notes': student.medical_notes,
        'created_at': student.created_at.isoformat(),
        'updated_at': student.updated_at.isoformat(),
    }


def class_to_dict(dance_class) -> dict:
    return {
        'id': dance_class.id,
        'name': dance_class.name,
        'description': dance_class.description,
        'location_id': dance_class.location_id,
        'location_name': dance_class.location.name if dance_class.location else None,
        'day_of_week': dance_class.day_of_week,
        'day_name': dance_class.day_name,
        'start_time': dance_class.start_time.strftime('%H:%M'),
        'end_time': dance_class.end_time.strftime('%H:%M'),
        'instructor_id': dance_class.instructor_id,
        'instructor_name': dance_class.instructor.full_name,
        'max_students': dance_class.max_students,
        'enrolled_count': dance_class.enrolled_students_count,
        'level': dance_class.level,
        'age_group': dance_class.age_group,
        'is_active': dance_class.is_active,
        'created_at': dance_class.created_at.isoformat(),
        'updated_at': dance_class.updated_at.isoformat(),
    }


def attendance_to_dict(attendance) -> dict:
    return {
        'id': attendance.id,
        'student_id': attendance.student_id,
        'student_name': attendance.student.full_name,
        'class_id': attendance.class_id,
        'class_name': attendance.dance_class.name,
        'check_in_time': attendance.check_in_time.isoformat(),
        'check_out_time': attendance.check_out_time.isoformat() if attendance.check_out_time else None,
        'check_in_method': attendance.check_in_method,
        'notes': attendance.notes,
        'is_present': attendance.is_present,
        'attendance_date': attendance.attendance_date.isoformat(),
        'duration': str(attendance.duration) if attendance.duration else None,
    }


def transaction_to_dict(t) -> dict:
    return {
        'id': t.id,
        'student_id': t.student_id,
        'student_name': t.student.full_name,
        'type': t.type,
        'amount': str(t.amount),
        'category': t.category,
        'payment_method': t.payment_method if t.payment_method != 'n/a' else None,
        'description': t.description,
        'transaction_date': t.transaction_date.isoformat(),
        'created_by': t.creator.full_name if t.creator else None,
        'created_at': t.created_at.isoformat(),
    }


def recurring_to_dict(rc) -> dict:
    return {
        'id': rc.id,
        'class_id': rc.class_id,
        'class_name': rc.dance_class.name,
        'amount': str(rc.amount),
        'category': rc.category,
        'description': rc.description,
        'day_of_month': rc.day_of_month,
        'is_active': rc.is_active,
        'created_at': rc.created_at.isoformat(),
    }


# Student fields that accept simple string-or-None values
STUDENT_STRING_FIELDS = [
    'first_name', 'last_name', 'email', 'phone',
    'emergency_contact_name', 'emergency_contact_phone', 'parent_email',
    'school', 'grade', 'allergies', 'special_needs',
    'height', 'weight', 'shoe_size', 'shirt_size', 'pants_size',
    'leotard_size', 'dress_size', 'waist', 'girth', 'inseam',
    'neck', 'tight_size', 'bust', 'hips', 'sleeve', 'chest',
    'size_notes', 'notes', 'medical_notes',
]


def apply_student_fields(student, data: dict) -> None:
    """Apply data dict fields to a Student instance. Strips strings, converts empties to None."""
    from datetime import datetime

    for field in STUDENT_STRING_FIELDS:
        if field in data:
            val = data[field]
            setattr(student, field, val.strip() or None if val else None)

    if 'date_of_birth' in data:
        dob = data['date_of_birth']
        student.date_of_birth = datetime.strptime(dob, '%Y-%m-%d').date() if dob else None

    if 'family_id' in data:
        student.family_id = int(data['family_id']) if data['family_id'] else None

    if 'is_active' in data:
        student.is_active = bool(data['is_active'])
