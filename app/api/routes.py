"""REST API routes for AttenDANCE system."""

import logging
import secrets
from datetime import date, datetime, timedelta

from flask import current_app, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import desc, func

from app import db, square_service
from app.api import bp
from app.helpers import (
    allocate_family_payment,
    apply_student_fields,
    attendance_to_dict,
    build_ledger,
    calc_balance,
    calc_balance_bulk,
    class_to_dict,
    recurring_to_dict,
    student_to_dict,
    transaction_to_dict,
)
from app.models import (
    Attendance,
    AuditLog,
    ClassEnrollment,
    DanceClass,
    Family,
    Location,
    Message,
    ParentStudent,
    PendingPayment,
    RecurringCharge,
    Rule,
    RuleAcknowledgment,
    Setting,
    SquareInvoice,
    Student,
    Transaction,
    User,
)

try:
    from rfid.service import get_rfid_service
except ImportError:
    get_rfid_service = None

logger = logging.getLogger(__name__)


# ── Auth endpoints ──────────────────────────────────────────────────

@bp.route('/auth/login', methods=['POST'])
def api_login():
    return jsonify({'message': 'Use /auth/login endpoint'}), 400


@bp.route('/auth/logout', methods=['POST'])
@login_required
def api_logout():
    return jsonify({'message': 'Use /auth/logout endpoint'}), 400


@bp.route('/auth/me')
@login_required
def api_current_user():
    return jsonify({
        'id': current_user.id,
        'username': current_user.username,
        'email': current_user.email,
        'full_name': current_user.full_name,
        'first_name': current_user.first_name,
        'last_name': current_user.last_name,
        'is_admin': current_user.is_admin,
        'last_login': current_user.last_login.isoformat() if current_user.last_login else None,
    })


# ── Student endpoints ───────────────────────────────────────────────

@bp.route('/students', methods=['GET'])
@login_required
def get_students():
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    search = request.args.get('search', '').strip()
    active_only = request.args.get('active', 'true').lower() == 'true'

    query = Student.query
    if active_only:
        query = query.filter_by(is_active=True)
    if search:
        query = query.filter(
            Student.first_name.contains(search)
            | Student.last_name.contains(search)
            | Student.email.contains(search)
        )
    query = query.order_by(Student.last_name, Student.first_name)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'students': [student_to_dict(s) for s in pagination.items],
        'pagination': {
            'page': page,
            'pages': pagination.pages,
            'per_page': per_page,
            'total': pagination.total,
            'has_next': pagination.has_next,
            'has_prev': pagination.has_prev,
        },
    })


@bp.route('/students/<int:student_id>', methods=['GET'])
@login_required
def get_student(student_id):
    return jsonify(student_to_dict(Student.query.get_or_404(student_id)))


@bp.route('/students', methods=['POST'])
@login_required
def create_student():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    for field in ('first_name', 'last_name'):
        if not data.get(field):
            return jsonify({'error': f'{field} is required'}), 400

    if data.get('email'):
        if Student.query.filter_by(email=data['email']).first():
            return jsonify({'error': 'Email already exists'}), 400

    try:
        student = Student()
        apply_student_fields(student, data)
        db.session.add(student)
        db.session.commit()
        return jsonify(student_to_dict(student)), 201
    except Exception:
        db.session.rollback()
        logger.exception("Failed to create student")
        return jsonify({'error': 'An internal error occurred'}), 500


@bp.route('/students/<int:student_id>', methods=['PUT'])
@login_required
def update_student(student_id):
    student = Student.query.get_or_404(student_id)
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    # Check email uniqueness if changing
    if 'email' in data:
        email = (data['email'] or '').strip() or None
        if email and email != student.email:
            if Student.query.filter_by(email=email).first():
                return jsonify({'error': 'Email already exists'}), 400

    try:
        apply_student_fields(student, data)
        student.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify(student_to_dict(student))
    except Exception:
        db.session.rollback()
        logger.exception("Failed to update student %d", student_id)
        return jsonify({'error': 'An internal error occurred'}), 500


@bp.route('/students/<int:student_id>', methods=['DELETE'])
@login_required
def delete_student(student_id):
    student = Student.query.get_or_404(student_id)
    student.is_active = False
    student.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'message': 'Student deactivated successfully'})


@bp.route('/students/<int:student_id>/assign-rfid', methods=['POST'])
@login_required
def assign_rfid(student_id):
    student = Student.query.get_or_404(student_id)
    data = request.get_json()
    rfid_uid = data.get('rfid_uid', '').strip() if data else ''
    if not rfid_uid:
        return jsonify({'error': 'RFID UID is required'}), 400

    existing = Student.query.filter_by(rfid_uid=rfid_uid).first()
    if existing and existing.id != student_id:
        return jsonify({'error': 'RFID card is already assigned to another student'}), 400

    student.rfid_uid = rfid_uid
    student.rfid_assigned_at = datetime.utcnow()
    student.rfid_assigned_by = current_user.id
    student.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({'message': 'RFID card assigned successfully', 'student': student_to_dict(student)})


@bp.route('/students/<int:student_id>/remove-rfid', methods=['POST'])
@login_required
def remove_rfid(student_id):
    student = Student.query.get_or_404(student_id)
    student.rfid_uid = None
    student.rfid_assigned_at = None
    student.rfid_assigned_by = None
    student.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'message': 'RFID card removed successfully', 'student': student_to_dict(student)})


# ── Class endpoints ─────────────────────────────────────────────────

@bp.route('/classes', methods=['GET'])
@login_required
def get_classes():
    active_only = request.args.get('active', 'true').lower() == 'true'
    query = DanceClass.query
    if active_only:
        query = query.filter_by(is_active=True)
    query = query.order_by(DanceClass.day_of_week, DanceClass.start_time)
    return jsonify({'classes': [class_to_dict(cls) for cls in query.all()]})


@bp.route('/classes/<int:class_id>', methods=['GET'])
@login_required
def get_class(class_id):
    return jsonify(class_to_dict(DanceClass.query.get_or_404(class_id)))


@bp.route('/classes', methods=['POST'])
@login_required
def create_class():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    for field in ('name', 'day_of_week', 'start_time', 'end_time'):
        if field not in data:
            return jsonify({'error': f'{field} is required'}), 400

    try:
        dance_class = DanceClass(
            name=data['name'].strip(),
            description=data.get('description', '').strip() or None,
            location_id=int(data['location_id']) if data.get('location_id') else None,
            day_of_week=int(data['day_of_week']),
            start_time=datetime.strptime(data['start_time'], '%H:%M').time(),
            end_time=datetime.strptime(data['end_time'], '%H:%M').time(),
            instructor_id=int(data.get('instructor_id', current_user.id)),
            max_students=data.get('max_students', 20),
            level=data.get('level', '').strip() or None,
            age_group=data.get('age_group', '').strip() or None,
        )
        db.session.add(dance_class)
        db.session.commit()
        return jsonify(class_to_dict(dance_class)), 201
    except Exception:
        db.session.rollback()
        logger.exception("Failed to create class")
        return jsonify({'error': 'An internal error occurred'}), 500


# ── Enrollment endpoints ────────────────────────────────────────────

@bp.route('/classes/<int:class_id>/enrollments', methods=['GET'])
@login_required
def get_class_enrollments(class_id):
    dance_class = DanceClass.query.get_or_404(class_id)
    enrollments = (
        ClassEnrollment.query
        .filter_by(class_id=class_id, is_active=True)
        .all()
    )
    students = []
    for e in enrollments:
        s = e.student
        if s:
            students.append({
                'enrollment_id': e.id,
                'student_id': s.id,
                'full_name': s.full_name,
                'email': s.email,
                'has_rfid': s.has_rfid(),
                'enrolled_date': e.enrolled_date.isoformat(),
            })
    return jsonify({'enrollments': students, 'class_name': dance_class.name})


@bp.route('/classes/<int:class_id>/enroll', methods=['POST'])
@login_required
def enroll_student(class_id):
    dance_class = DanceClass.query.get_or_404(class_id)
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    student_ids = data.get('student_ids', [])
    if not student_ids and data.get('student_id'):
        student_ids = [int(data['student_id'])]
    if not student_ids:
        return jsonify({'error': 'student_id or student_ids is required'}), 400

    enrolled = []
    skipped = []
    for sid in student_ids:
        student = Student.query.get(int(sid))
        if not student:
            continue
        existing = ClassEnrollment.query.filter_by(
            student_id=student.id, class_id=class_id
        ).first()
        if existing:
            if existing.is_active:
                skipped.append(student.full_name)
                continue
            existing.is_active = True
            existing.enrolled_date = date.today()
        else:
            db.session.add(ClassEnrollment(student_id=student.id, class_id=class_id))
        enrolled.append(student.full_name)

    db.session.commit()
    msg = f'{len(enrolled)} student(s) enrolled in {dance_class.name}'
    if skipped:
        msg += f' ({len(skipped)} already enrolled)'
    return jsonify({'message': msg, 'enrolled': enrolled, 'skipped': skipped}), 201


@bp.route('/enrollments/<int:enrollment_id>', methods=['DELETE'])
@login_required
def unenroll_student(enrollment_id):
    enrollment = ClassEnrollment.query.get_or_404(enrollment_id)
    enrollment.is_active = False
    db.session.commit()
    return jsonify({'message': 'Student unenrolled successfully'})


# ── Attendance endpoints ────────────────────────────────────────────

@bp.route('/attendance/toggle', methods=['POST'])
@login_required
def toggle_attendance():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    student_id = data.get('student_id')
    class_id = data.get('class_id')
    if not all([student_id, class_id]):
        return jsonify({'error': 'student_id and class_id required'}), 400

    att_date = data.get('date')
    target_date = datetime.strptime(att_date, '%Y-%m-%d').date() if att_date else date.today()

    existing = Attendance.query.filter(
        Attendance.student_id == student_id,
        Attendance.class_id == class_id,
        func.date(Attendance.check_in_time) == target_date,
    ).first()

    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({'present': False, 'message': 'Attendance removed'})

    att = Attendance(
        student_id=student_id,
        class_id=class_id,
        check_in_time=datetime.combine(target_date, datetime.now().time()),
        check_in_method='manual',
        is_present=True,
    )
    db.session.add(att)
    db.session.commit()
    return jsonify({'present': True, 'message': 'Marked present'}), 201


@bp.route('/attendance', methods=['GET'])
@login_required
def get_attendance():
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 100)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    class_id = request.args.get('class_id', type=int)
    student_id = request.args.get('student_id', type=int)

    query = Attendance.query
    if date_from:
        query = query.filter(func.date(Attendance.check_in_time) >= datetime.strptime(date_from, '%Y-%m-%d').date())
    if date_to:
        query = query.filter(func.date(Attendance.check_in_time) <= datetime.strptime(date_to, '%Y-%m-%d').date())
    if class_id:
        query = query.filter_by(class_id=class_id)
    if student_id:
        query = query.filter_by(student_id=student_id)
    query = query.order_by(desc(Attendance.check_in_time))
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'attendance': [attendance_to_dict(att) for att in pagination.items],
        'pagination': {
            'page': page,
            'pages': pagination.pages,
            'per_page': per_page,
            'total': pagination.total,
            'has_next': pagination.has_next,
            'has_prev': pagination.has_prev,
        },
    })


@bp.route('/attendance/today', methods=['GET'])
@login_required
def get_todays_attendance():
    today = date.today()
    class_id = request.args.get('class_id', type=int)
    query = Attendance.query.filter(func.date(Attendance.check_in_time) == today)
    if class_id:
        query = query.filter_by(class_id=class_id)
    records = query.order_by(desc(Attendance.check_in_time)).all()
    return jsonify({
        'date': today.isoformat(),
        'attendance': [attendance_to_dict(att) for att in records],
        'count': len(records),
    })


@bp.route('/attendance/checkin', methods=['POST'])
@login_required
def manual_checkin():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    student_id = data.get('student_id')
    class_id = data.get('class_id')
    if not student_id or not class_id:
        return jsonify({'error': 'student_id and class_id are required'}), 400

    student = Student.query.get_or_404(student_id)
    DanceClass.query.get_or_404(class_id)

    today = date.today()
    existing = Attendance.query.filter(
        Attendance.student_id == student_id,
        Attendance.class_id == class_id,
        func.date(Attendance.check_in_time) == today,
    ).first()
    if existing:
        return jsonify({'error': 'Student already checked in today'}), 400

    try:
        att = Attendance(
            student_id=student_id,
            class_id=class_id,
            check_in_time=datetime.utcnow(),
            check_in_method='manual',
            notes=data.get('notes', '').strip() or None,
            is_present=True,
        )
        db.session.add(att)
        db.session.commit()
        return jsonify({
            'message': f'{student.full_name} checked in successfully',
            'attendance': attendance_to_dict(att),
        }), 201
    except Exception:
        db.session.rollback()
        logger.exception("Failed to check in student %d", student_id)
        return jsonify({'error': 'An internal error occurred'}), 500


# ── RFID endpoints ──────────────────────────────────────────────────

@bp.route('/rfid/status', methods=['GET'])
@login_required
def rfid_status():
    if not get_rfid_service:
        return jsonify({'service_running': False, 'message': 'RFID not available'})
    stats = get_rfid_service().get_stats()
    return jsonify({
        'service_running': stats['running'],
        'total_scans': stats['total_scans'],
        'successful_checkins': stats['successful_checkins'],
        'failed_scans': stats['failed_scans'],
        'last_scan_time': stats['last_scan_time'].isoformat() if stats['last_scan_time'] else None,
        'last_scan_uid': stats['last_scan_uid'],
    })


@bp.route('/rfid/simulate', methods=['POST'])
@login_required
def simulate_rfid_scan():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.get_json()
    uid = data.get('uid') if data else None
    if not uid:
        return jsonify({'error': 'UID is required'}), 400
    if not get_rfid_service:
        return jsonify({'error': 'RFID not available'}), 400
    success = get_rfid_service().simulate_scan(uid)
    return jsonify({'success': success, 'message': f'Simulated scan for UID: {uid}'})


@bp.route('/rfid/logs', methods=['GET'])
@login_required
def get_rfid_logs():
    from app.models import RFIDLog

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 100)
    query = RFIDLog.query.order_by(desc(RFIDLog.scan_time))
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    logs = [{
        'id': log.id,
        'rfid_uid': log.rfid_uid,
        'student_id': log.student_id,
        'student_name': log.student.full_name if log.student else None,
        'scan_time': log.scan_time.isoformat(),
        'action_taken': log.action_taken,
        'success': log.success,
        'error_message': log.error_message,
    } for log in pagination.items]

    return jsonify({
        'logs': logs,
        'pagination': {
            'page': page,
            'pages': pagination.pages,
            'per_page': per_page,
            'total': pagination.total,
            'has_next': pagination.has_next,
            'has_prev': pagination.has_prev,
        },
    })


# ── Dashboard stats ─────────────────────────────────────────────────

@bp.route('/dashboard/stats', methods=['GET'])
@login_required
def dashboard_stats():
    from app.models import RFIDLog

    today = date.today()
    total_students = Student.query.filter_by(is_active=True).count()
    total_classes = DanceClass.query.filter_by(is_active=True).count()
    todays_attendance = Attendance.query.filter(
        func.date(Attendance.check_in_time) == today
    ).count()
    week_start = today - timedelta(days=today.weekday())
    week_attendance = Attendance.query.filter(
        func.date(Attendance.check_in_time) >= week_start
    ).count()
    recent_rfid_logs = RFIDLog.query.filter(
        RFIDLog.scan_time >= datetime.utcnow() - timedelta(days=1)
    ).count()

    return jsonify({
        'total_students': total_students,
        'total_classes': total_classes,
        'todays_attendance': todays_attendance,
        'week_attendance': week_attendance,
        'recent_rfid_activity': recent_rfid_logs,
        'date': today.isoformat(),
    })


# ── Transaction endpoints ───────────────────────────────────────────

@bp.route('/transactions', methods=['GET'])
@login_required
def get_transactions():
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 100)
    student_id = request.args.get('student_id', type=int)
    category = request.args.get('category', '').strip()

    query = Transaction.query
    if student_id:
        query = query.filter_by(student_id=student_id)
    if category:
        query = query.filter_by(category=category)
    query = query.order_by(desc(Transaction.transaction_date), desc(Transaction.created_at))
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'transactions': [transaction_to_dict(t) for t in pagination.items],
        'pagination': {
            'page': page,
            'pages': pagination.pages,
            'per_page': per_page,
            'total': pagination.total,
        },
    })


@bp.route('/transactions', methods=['POST'])
@login_required
def create_transaction():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    txn_type = data.get('type', 'payment')
    for field in ('student_id', 'amount', 'category'):
        if not data.get(field):
            return jsonify({'error': f'{field} is required'}), 400
    if txn_type == 'payment' and not data.get('payment_method'):
        return jsonify({'error': 'payment_method is required for payments'}), 400

    student = Student.query.get(data['student_id'])
    if not student:
        return jsonify({'error': 'Student not found'}), 404

    try:
        t = Transaction(
            student_id=student.id,
            type=txn_type,
            amount=data['amount'],
            category=data['category'],
            payment_method=data.get('payment_method') or 'n/a',
            description=data.get('description', '').strip() or None,
            transaction_date=(
                datetime.strptime(data['transaction_date'], '%Y-%m-%d').date()
                if data.get('transaction_date') else date.today()
            ),
            created_by=current_user.id,
        )
        db.session.add(t)
        db.session.commit()
        return jsonify(transaction_to_dict(t)), 201
    except Exception:
        db.session.rollback()
        logger.exception("Failed to create transaction")
        return jsonify({'error': 'An internal error occurred'}), 500


@bp.route('/balances', methods=['GET'])
@login_required
def get_balances():
    """Balance summary for all active students — single SQL aggregate."""
    students = Student.query.filter_by(is_active=True).order_by(Student.last_name, Student.first_name).all()
    student_ids = [s.id for s in students]
    balances_map = calc_balance_bulk(student_ids)

    balances = []
    for s in students:
        bal = balances_map[s.id]
        balances.append({
            'student_id': s.id,
            'student_name': s.full_name,
            'total_charges': f'{bal["total_charges"]:.2f}',
            'total_payments': f'{bal["total_payments"]:.2f}',
            'balance': f'{bal["balance"]:.2f}',
        })
    return jsonify({'balances': balances})


@bp.route('/students/<int:student_id>/ledger', methods=['GET'])
@login_required
def get_student_ledger(student_id):
    """Full ledger with running balance — single pass."""
    student = Student.query.get_or_404(student_id)
    txns = Transaction.query.filter_by(student_id=student_id).order_by(
        Transaction.transaction_date, Transaction.created_at
    ).all()
    result = build_ledger(txns)
    return jsonify({
        'student_id': student.id,
        'student_name': student.full_name,
        **result,
    })


@bp.route('/transactions/bulk-charge', methods=['POST'])
@login_required
def bulk_charge():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    for field in ('class_id', 'amount', 'category'):
        if not data.get(field):
            return jsonify({'error': f'{field} is required'}), 400

    dance_class = DanceClass.query.get(data['class_id'])
    if not dance_class:
        return jsonify({'error': 'Class not found'}), 404

    enrollments = ClassEnrollment.query.filter_by(class_id=dance_class.id, is_active=True).all()
    if not enrollments:
        return jsonify({'error': 'No students enrolled in this class'}), 400

    txn_date = (
        datetime.strptime(data['transaction_date'], '%Y-%m-%d').date()
        if data.get('transaction_date') else date.today()
    )
    charged = []
    for e in enrollments:
        t = Transaction(
            student_id=e.student_id,
            type='charge',
            amount=data['amount'],
            category=data['category'],
            payment_method='n/a',
            description=data.get('description', '').strip() or f'{dance_class.name} - {data["category"]}',
            transaction_date=txn_date,
            created_by=current_user.id,
        )
        db.session.add(t)
        charged.append(e.student_id)
    db.session.commit()
    return jsonify({'message': f'Charged {len(charged)} students', 'count': len(charged)}), 201


# ── Recurring charge endpoints ──────────────────────────────────────

@bp.route('/recurring-charges', methods=['GET'])
@login_required
def get_recurring_charges():
    charges = RecurringCharge.query.order_by(RecurringCharge.created_at).all()
    return jsonify({'recurring_charges': [recurring_to_dict(rc) for rc in charges]})


@bp.route('/recurring-charges', methods=['POST'])
@login_required
def create_recurring_charge():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    for field in ('class_id', 'amount', 'category'):
        if not data.get(field):
            return jsonify({'error': f'{field} is required'}), 400

    dance_class = DanceClass.query.get(data['class_id'])
    if not dance_class:
        return jsonify({'error': 'Class not found'}), 404

    day = int(data.get('day_of_month', 1))
    if day < 1 or day > 28:
        return jsonify({'error': 'day_of_month must be 1-28'}), 400

    rc = RecurringCharge(
        class_id=dance_class.id,
        amount=data['amount'],
        category=data['category'],
        description=data.get('description', '').strip() or None,
        day_of_month=day,
        created_by=current_user.id,
    )
    db.session.add(rc)
    db.session.commit()
    return jsonify(recurring_to_dict(rc)), 201


@bp.route('/recurring-charges/<int:rc_id>', methods=['DELETE'])
@login_required
def delete_recurring_charge(rc_id):
    rc = RecurringCharge.query.get_or_404(rc_id)
    rc.is_active = False
    db.session.commit()
    return jsonify({'message': 'Recurring charge deactivated'})


@bp.route('/recurring-charges/process', methods=['POST'])
@login_required
def process_recurring_charges():
    from app import _process_recurring_charges
    _process_recurring_charges()
    return jsonify({'message': 'Recurring charges processed'})


# ── Square payment endpoints ────────────────────────────────────────

@bp.route('/square/status', methods=['GET'])
@login_required
def square_status():
    return jsonify({'configured': square_service.is_configured()})


@bp.route('/students/<int:student_id>/send-invoice', methods=['POST'])
@login_required
def send_student_invoice(student_id):
    if not square_service.is_configured():
        return jsonify({'error': 'Square is not configured. Set SQUARE_ACCESS_TOKEN and SQUARE_LOCATION_ID in environment.'}), 400

    student = Student.query.get_or_404(student_id)
    bal = calc_balance(student_id)

    if bal['balance'] <= 0:
        return jsonify({'error': 'No outstanding balance to invoice'}), 400

    # Build line items from charges
    charges = Transaction.query.filter_by(student_id=student_id, type='charge').all()
    line_items = [{
        'name': t.description or t.category,
        'amount_cents': int(float(t.amount) * 100),
    } for t in charges]

    due = date.today() + timedelta(days=14)
    amount_cents = int(round(bal['balance'] * 100))
    try:
        result = square_service.send_invoice(
            student=student,
            amount_cents=amount_cents,
            line_items=line_items,
            due_date=due,
        )
        # Persist so the webhook can auto-record the payment when paid
        inv = SquareInvoice(
            student_id=student.id,
            invoice_id=result['invoice_id'],
            amount_cents=amount_cents,
            status=result.get('status', 'SENT'),
            public_url=result.get('invoice_url', ''),
        )
        db.session.add(inv)
        AuditLog.record(current_user.id, 'invoice.send',
                        f'Square invoice ${bal["balance"]:.2f} to {student.full_name} '
                        f'({student.parent_email or student.email})')
        db.session.commit()
        return jsonify({
            'message': f'Invoice sent to {student.parent_email or student.email}',
            'invoice_url': result['invoice_url'],
            'invoice_id': result['invoice_id'],
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ── Parent invite endpoints ─────────────────────────────────────────

@bp.route('/students/<int:student_id>/invite-parent', methods=['POST'])
@login_required
def invite_parent(student_id):
    if current_user.is_parent:
        return jsonify({'error': 'Only staff can generate invites'}), 403

    student = Student.query.get_or_404(student_id)

    # Check if parent already linked
    existing_parent = (
        User.query
        .join(ParentStudent, ParentStudent.parent_id == User.id)
        .filter(ParentStudent.student_id == student_id, User.is_active == True)  # noqa: E712
        .first()
    )
    if existing_parent:
        return jsonify({
            'error': f'Parent already linked: {existing_parent.full_name} ({existing_parent.email})'
        }), 400

    code = secrets.token_hex(4).upper()
    parent_user = User(
        username=f'parent-{code}',
        email=f'invite-{code}@pending.local',
        first_name='Pending',
        last_name='Parent',
        password_hash='not-set',
        role='parent',
        is_active=False,
        invite_code=code,
    )
    db.session.add(parent_user)
    db.session.flush()

    link = ParentStudent(parent_id=parent_user.id, student_id=student_id)
    db.session.add(link)
    db.session.commit()

    return jsonify({
        'invite_code': code,
        'message': f'Invite code generated for {student.full_name}. Share this with the parent: {code}',
        'register_url': f'/auth/register?code={code}',
    }), 201


@bp.route('/seed-demo-parent', methods=['POST'])
@login_required
def seed_demo_parent():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    student = Student.query.first()
    if not student:
        return jsonify({'error': 'No students found'}), 400

    existing = User.query.filter_by(username='parent-demo').first()
    if existing:
        ParentStudent.query.filter_by(parent_id=existing.id).delete()
        db.session.delete(existing)
        db.session.commit()

    p = User(
        username='parent-demo', email='parent@demo.local',
        first_name='Demo', last_name='Parent', role='parent', is_active=True,
    )
    p.set_password('parent123')
    db.session.add(p)
    db.session.flush()
    db.session.add(ParentStudent(parent_id=p.id, student_id=student.id))
    db.session.commit()
    return jsonify({
        'message': f'Parent account created: parent-demo / parent123, linked to {student.full_name}'
    })


# ── Rules & Regulations endpoints ──────────────────────────────────

@bp.route('/rules', methods=['GET'])
@login_required
def get_rules():
    rules = Rule.query.filter_by(is_active=True).order_by(Rule.display_order).all()
    return jsonify({'rules': [
        {'id': r.id, 'text': r.text, 'display_order': r.display_order}
        for r in rules
    ]})


@bp.route('/rules', methods=['POST'])
@login_required
def create_rule():
    data = request.get_json()
    if not data or not data.get('text'):
        return jsonify({'error': 'text is required'}), 400
    max_order = db.session.query(func.max(Rule.display_order)).scalar() or 0
    r = Rule(text=data['text'].strip(), display_order=max_order + 1)
    db.session.add(r)
    db.session.commit()
    return jsonify({'id': r.id, 'text': r.text, 'display_order': r.display_order}), 201


@bp.route('/rules/<int:rule_id>', methods=['PUT'])
@login_required
def update_rule(rule_id):
    r = Rule.query.get_or_404(rule_id)
    data = request.get_json()
    if data.get('text'):
        r.text = data['text'].strip()
    if 'display_order' in data:
        r.display_order = int(data['display_order'])
    db.session.commit()
    return jsonify({'id': r.id, 'text': r.text, 'display_order': r.display_order})


@bp.route('/rules/<int:rule_id>', methods=['DELETE'])
@login_required
def delete_rule(rule_id):
    r = Rule.query.get_or_404(rule_id)
    r.is_active = False
    db.session.commit()
    return jsonify({'message': 'Rule removed'})


@bp.route('/students/<int:student_id>/rules-status', methods=['GET'])
@login_required
def get_student_rules_status(student_id):
    student = Student.query.get_or_404(student_id)
    rules = Rule.query.filter_by(is_active=True).order_by(Rule.display_order).all()
    acks = RuleAcknowledgment.query.filter_by(student_id=student_id).all()
    ack_map = {a.rule_id: a for a in acks}

    result = []
    for r in rules:
        ack = ack_map.get(r.id)
        result.append({
            'rule_id': r.id, 'text': r.text, 'display_order': r.display_order,
            'acknowledged': ack is not None,
            'initials': ack.initials if ack else None,
            'acknowledged_at': ack.acknowledged_at.isoformat() if ack else None,
        })

    active_rule_ids = {r.id for r in rules}
    done = sum(1 for rid in ack_map if rid in active_rule_ids)
    total = len(rules)

    return jsonify({
        'student_name': student.full_name,
        'rules': result,
        'total': total, 'acknowledged': done,
        'complete': done == total and total > 0,
    })


@bp.route('/rules/<int:rule_id>/acknowledge', methods=['POST'])
@login_required
def acknowledge_rule(rule_id):
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    student_id = data.get('student_id')
    initials = data.get('initials', '').strip()
    if not student_id or not initials:
        return jsonify({'error': 'student_id and initials are required'}), 400

    Rule.query.get_or_404(rule_id)
    Student.query.get_or_404(student_id)

    existing = RuleAcknowledgment.query.filter_by(
        rule_id=rule_id, student_id=student_id, parent_id=current_user.id
    ).first()
    if existing:
        return jsonify({'message': 'Already acknowledged'})

    ack = RuleAcknowledgment(
        rule_id=rule_id, student_id=student_id,
        parent_id=current_user.id, initials=initials.upper(),
    )
    db.session.add(ack)
    db.session.commit()
    return jsonify({'message': 'Rule acknowledged', 'initials': ack.initials}), 201


# ── Message / Email blast endpoints ─────────────────────────────────

@bp.route('/messages', methods=['GET'])
@login_required
def get_messages():
    msgs = Message.query.order_by(desc(Message.created_at)).limit(50).all()
    return jsonify({'messages': [{
        'id': m.id, 'subject': m.subject, 'body': m.body,
        'recipient_type': m.recipient_type, 'recipient_filter': m.recipient_filter,
        'recipient_count': m.recipient_count, 'recipient_emails': m.recipient_emails,
        'sent': m.sent, 'sent_at': m.sent_at.isoformat() if m.sent_at else None,
        'created_by': m.creator.full_name if m.creator else None,
        'created_at': m.created_at.isoformat(),
    } for m in msgs]})


@bp.route('/messages', methods=['POST'])
@login_required
def send_message():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    for field in ('subject', 'body', 'recipient_type'):
        if not data.get(field):
            return jsonify({'error': f'{field} is required'}), 400

    rtype = data['recipient_type']
    emails = _resolve_recipient_emails(rtype, data.get('recipient_filter'))
    if isinstance(emails, tuple):
        return emails  # error response

    if not emails:
        return jsonify({'error': 'No email addresses found for selected recipients'}), 400

    msg = Message(
        subject=data['subject'].strip(),
        body=data['body'].strip(),
        recipient_type=rtype,
        recipient_filter=str(data.get('recipient_filter', '')),
        recipient_count=len(emails),
        recipient_emails=', '.join(sorted(emails)),
        created_by=current_user.id,
    )

    from app import email as email_service
    if email_service.is_configured():
        try:
            email_service.send_email(emails, data['subject'].strip(), data['body'].strip())
            msg.sent = True
            msg.sent_at = datetime.utcnow()
        except Exception as e:
            msg.sent = False
            db.session.add(msg)
            db.session.commit()
            return jsonify({
                'error': f'SMTP send failed: {e}',
                'message_id': msg.id,
                'recipient_emails': sorted(emails),
                'saved': True,
            }), 500
    else:
        msg.sent = False

    db.session.add(msg)
    db.session.commit()

    if msg.sent:
        return jsonify({'message': f'Email sent to {len(emails)} recipient(s)', 'message_id': msg.id}), 201

    reply_to = current_app.config.get('MAIL_REPLY_TO', '')
    return jsonify({
        'message': 'Message saved (SMTP not configured — copy emails below to send manually)',
        'message_id': msg.id,
        'recipient_emails': sorted(emails),
        'recipient_count': len(emails),
        'reply_to': reply_to,
    }), 201


def _resolve_recipient_emails(rtype: str, recipient_filter) -> set | tuple:
    """Resolve email addresses for a message. Returns a set of emails or an error tuple."""
    emails: set[str] = set()
    if rtype == 'all':
        for s in Student.query.filter_by(is_active=True).all():
            if s.parent_email:
                emails.add(s.parent_email)
            elif s.email:
                emails.add(s.email)
    elif rtype == 'class':
        if not recipient_filter:
            return jsonify({'error': 'recipient_filter (class_id) required for class type'}), 400
        # Use join to avoid N+1
        rows = (
            db.session.query(Student.parent_email, Student.email)
            .join(ClassEnrollment, ClassEnrollment.student_id == Student.id)
            .filter(ClassEnrollment.class_id == int(recipient_filter), ClassEnrollment.is_active == True)  # noqa: E712
            .all()
        )
        for parent_email, student_email in rows:
            if parent_email:
                emails.add(parent_email)
            elif student_email:
                emails.add(student_email)
    elif rtype == 'individual':
        if not recipient_filter:
            return jsonify({'error': 'recipient_filter (student_id) required for individual type'}), 400
        s = Student.query.get(int(recipient_filter))
        if s and (s.parent_email or s.email):
            emails.add(s.parent_email or s.email)
    return emails


# ── Family endpoints ────────────────────────────────────────────────

@bp.route('/families', methods=['GET'])
@login_required
def get_families():
    """Get all families with balances — bulk query."""
    families = Family.query.filter_by(is_active=True).order_by(Family.name).all()

    # Collect all student IDs across all families
    family_students: dict[int, list] = {}
    all_student_ids: list[int] = []
    for f in families:
        students = f.students.filter_by(is_active=True).all()
        family_students[f.id] = students
        all_student_ids.extend(s.id for s in students)

    # Single bulk balance query
    balances_map = calc_balance_bulk(all_student_ids)

    result = []
    for f in families:
        students = family_students[f.id]
        total_charges = sum(balances_map[s.id]['total_charges'] for s in students)
        total_payments = sum(balances_map[s.id]['total_payments'] for s in students)
        result.append({
            'id': f.id, 'name': f.name,
            'primary_email': f.primary_email, 'primary_phone': f.primary_phone,
            'student_count': len(students),
            'students': [{'id': s.id, 'full_name': s.full_name} for s in students],
            'total_charges': f'{total_charges:.2f}',
            'total_payments': f'{total_payments:.2f}',
            'balance': f'{total_charges - total_payments:.2f}',
        })
    return jsonify({'families': result})


@bp.route('/families', methods=['POST'])
@login_required
def create_family():
    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({'error': 'name is required'}), 400
    f = Family(
        name=data['name'].strip(),
        primary_email=data.get('primary_email', '').strip() or None,
        primary_phone=data.get('primary_phone', '').strip() or None,
    )
    db.session.add(f)
    db.session.commit()
    return jsonify({'id': f.id, 'name': f.name}), 201


@bp.route('/families/<int:family_id>/ledger', methods=['GET'])
@login_required
def get_family_ledger(family_id):
    """Combined ledger for all students in a family — single pass."""
    family = Family.query.get_or_404(family_id)
    students = family.students.filter_by(is_active=True).all()
    student_ids = [s.id for s in students]

    all_txns = (
        Transaction.query
        .filter(Transaction.student_id.in_(student_ids))
        .order_by(Transaction.transaction_date, Transaction.created_at)
        .all()
    ) if student_ids else []

    result = build_ledger(all_txns)
    return jsonify({
        'family_id': family.id, 'family_name': family.name,
        'students': [{'id': s.id, 'full_name': s.full_name} for s in students],
        **result,
    })


# ── Staff / Teacher endpoints (admin only) ──────────────────────────

def _staff_to_dict(u):
    return {
        'id': u.id,
        'username': u.username,
        'email': u.email,
        'first_name': u.first_name,
        'last_name': u.last_name,
        'full_name': u.full_name,
        'phone': u.phone,
        'role': u.role,
        'is_admin': u.is_admin,
        'is_active': u.is_active,
        'last_login': u.last_login.isoformat() if u.last_login else None,
        'created_at': u.created_at.isoformat(),
    }


@bp.route('/staff', methods=['GET'])
@login_required
def get_staff():
    """Get all staff (admin + teacher) users."""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    users = User.query.filter(User.role.in_(['admin', 'teacher'])).order_by(User.last_name, User.first_name).all()
    return jsonify({'staff': [_staff_to_dict(u) for u in users]})


@bp.route('/staff', methods=['POST'])
@login_required
def create_staff():
    """Create a new teacher or admin user."""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    for field in ('first_name', 'last_name', 'email', 'username', 'password'):
        if not data.get(field):
            return jsonify({'error': f'{field} is required'}), 400

    if User.query.filter_by(username=data['username'].strip()).first():
        return jsonify({'error': 'Username already taken'}), 400
    if User.query.filter_by(email=data['email'].strip()).first():
        return jsonify({'error': 'Email already in use'}), 400

    role = data.get('role', 'teacher')
    if role not in ('admin', 'teacher'):
        return jsonify({'error': 'Role must be admin or teacher'}), 400

    u = User(
        username=data['username'].strip(),
        email=data['email'].strip(),
        first_name=data['first_name'].strip(),
        last_name=data['last_name'].strip(),
        phone=data.get('phone', '').strip() or None,
        role=role,
        is_admin=(role == 'admin'),
        is_active=True,
    )
    u.set_password(data['password'])
    db.session.add(u)
    db.session.commit()
    return jsonify(_staff_to_dict(u)), 201


@bp.route('/staff/<int:user_id>', methods=['PUT'])
@login_required
def update_staff(user_id):
    """Update a staff user."""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    u = User.query.get_or_404(user_id)
    if u.role not in ('admin', 'teacher'):
        return jsonify({'error': 'Not a staff user'}), 400
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    if 'first_name' in data:
        u.first_name = data['first_name'].strip()
    if 'last_name' in data:
        u.last_name = data['last_name'].strip()
    if 'email' in data:
        email = data['email'].strip()
        if email != u.email and User.query.filter_by(email=email).first():
            return jsonify({'error': 'Email already in use'}), 400
        u.email = email
    if 'phone' in data:
        u.phone = data['phone'].strip() or None
    if 'role' in data:
        role = data['role']
        if role not in ('admin', 'teacher'):
            return jsonify({'error': 'Role must be admin or teacher'}), 400
        u.role = role
        u.is_admin = (role == 'admin')
    if data.get('password'):
        u.set_password(data['password'])

    db.session.commit()
    return jsonify(_staff_to_dict(u))


@bp.route('/staff/<int:user_id>', methods=['DELETE'])
@login_required
def deactivate_staff(user_id):
    """Deactivate a staff user (soft delete)."""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    u = User.query.get_or_404(user_id)
    if u.id == current_user.id:
        return jsonify({'error': 'Cannot deactivate your own account'}), 400
    u.is_active = False
    db.session.commit()
    return jsonify({'message': f'{u.full_name} deactivated'})


# ── Location endpoints ──────────────────────────────────────────────

def _location_to_dict(loc):
    return {
        'id': loc.id,
        'name': loc.name,
        'address': loc.address,
        'city': loc.city,
        'state': loc.state,
        'zip_code': loc.zip_code,
        'full_address': loc.full_address,
        'phone': loc.phone,
        'notes': loc.notes,
        'is_active': loc.is_active,
        'class_count': loc.classes.filter_by(is_active=True).count(),
        'created_at': loc.created_at.isoformat(),
    }


@bp.route('/locations', methods=['GET'])
@login_required
def get_locations():
    """Get all locations."""
    locations = Location.query.filter_by(is_active=True).order_by(Location.name).all()
    return jsonify({'locations': [_location_to_dict(loc) for loc in locations]})


@bp.route('/locations', methods=['POST'])
@login_required
def create_location():
    """Create a new location (admin only)."""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({'error': 'name is required'}), 400

    loc = Location(
        name=data['name'].strip(),
        address=data.get('address', '').strip() or None,
        city=data.get('city', '').strip() or None,
        state=data.get('state', '').strip() or None,
        zip_code=data.get('zip_code', '').strip() or None,
        phone=data.get('phone', '').strip() or None,
        notes=data.get('notes', '').strip() or None,
    )
    db.session.add(loc)
    db.session.commit()
    return jsonify(_location_to_dict(loc)), 201


@bp.route('/locations/<int:location_id>', methods=['PUT'])
@login_required
def update_location(location_id):
    """Update a location."""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    loc = Location.query.get_or_404(location_id)
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    for field in ('name', 'address', 'city', 'state', 'zip_code', 'phone', 'notes'):
        if field in data:
            val = data[field]
            setattr(loc, field, val.strip() or None if val else None)

    db.session.commit()
    return jsonify(_location_to_dict(loc))


@bp.route('/locations/<int:location_id>', methods=['DELETE'])
@login_required
def deactivate_location(location_id):
    """Deactivate a location."""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    loc = Location.query.get_or_404(location_id)
    loc.is_active = False
    db.session.commit()
    return jsonify({'message': f'{loc.name} deactivated'})


# ── Settings endpoints (admin only) ─────────────────────────────────

# Settings editable via the payments PUT endpoint
PAYMENT_SETTINGS_KEYS = [
    'payments_zelle_enabled', 'payments_zelle_name', 'payments_zelle_memo',
    'payments_cashapp_enabled', 'payments_cashapp_tag',
    'payments_square_enabled', 'payments_square_access_token',
    'payments_square_location_id', 'payments_square_environment',
    'payments_square_webhook_signature_key',
]

# Secret settings: encrypted at rest, masked on read
SECRET_SETTINGS_KEYS = {
    'payments_square_access_token',
    'payments_square_webhook_signature_key',
}

DEFAULT_ZELLE_MEMO = "Put your dancer's full name in the memo so we can match your payment."


def _admin_only():
    """Return an error response tuple if the current user isn't admin, else None."""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    return None


def _mask_secret(plaintext: str) -> str:
    if not plaintext:
        return ''
    if len(plaintext) > 12:
        return plaintext[:4] + '••••' + plaintext[-4:]
    return '••••'


@bp.route('/settings/payments', methods=['GET'])
@login_required
def get_payment_settings():
    """Get payment configuration. Secrets are decrypted then masked for display."""
    err = _admin_only()
    if err:
        return err
    from app.crypto import decrypt
    settings = {}
    for key in PAYMENT_SETTINGS_KEYS:
        raw = Setting.get(key, '')
        if key in SECRET_SETTINGS_KEYS:
            settings[key] = _mask_secret(decrypt(raw))
        else:
            settings[key] = raw
    if not settings.get('payments_zelle_memo'):
        settings['payments_zelle_memo'] = DEFAULT_ZELLE_MEMO
    settings['has_zelle_qr'] = bool(Setting.get('payments_zelle_qr_data') or Setting.get('payments_zelle_qr_path'))
    settings['zelle_qr'] = Setting.get('payments_zelle_qr_data') or Setting.get('payments_zelle_qr_path', '')
    return jsonify({'settings': settings})


@bp.route('/settings/payments', methods=['PUT'])
@login_required
def update_payment_settings():
    """Update payment configuration. Secrets are encrypted before storage."""
    err = _admin_only()
    if err:
        return err
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    from app.crypto import encrypt
    changed = []
    for key in PAYMENT_SETTINGS_KEYS:
        if key not in data:
            continue
        val = (data[key] or '').strip()
        if key in SECRET_SETTINGS_KEYS:
            # Skip masked placeholders — means "leave unchanged"
            if not val or '••••' in val:
                continue
            Setting.set(key, encrypt(val))
            changed.append(key)
        else:
            Setting.set(key, val)
            changed.append(key)

    if changed:
        AuditLog.record(current_user.id, 'settings.update',
                        'Updated payment settings: ' + ', '.join(changed))
        db.session.commit()
    return jsonify({'message': 'Payment settings updated', 'changed': changed})


@bp.route('/settings/payments/zelle-qr', methods=['POST'])
@login_required
def upload_zelle_qr():
    """Upload Zelle QR code image — stored as a data URI in the DB so it
    survives redeploys (the filesystem on Fly is ephemeral)."""
    import base64
    err = _admin_only()
    if err:
        return err
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({'error': 'No file selected'}), 400

    raw = f.read()
    if len(raw) > 2 * 1024 * 1024:
        return jsonify({'error': 'Image too large (max 2MB)'}), 400

    content_type = (f.mimetype or '').lower()
    if not content_type.startswith('image/'):
        # Fall back to extension sniffing
        ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
        ext_map = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'gif': 'image/gif', 'webp': 'image/webp'}
        content_type = ext_map.get(ext, '')
        if not content_type:
            return jsonify({'error': 'File must be an image (PNG, JPG, GIF, or WebP)'}), 400

    data_uri = f'data:{content_type};base64,' + base64.b64encode(raw).decode('ascii')
    Setting.set('payments_zelle_qr_data', data_uri)
    AuditLog.record(current_user.id, 'settings.zelle_qr', 'Uploaded Zelle QR code')
    db.session.commit()
    return jsonify({'message': 'QR code uploaded', 'path': data_uri})


@bp.route('/settings/payments/zelle-qr', methods=['DELETE'])
@login_required
def delete_zelle_qr():
    """Remove the stored Zelle QR code."""
    err = _admin_only()
    if err:
        return err
    Setting.set('payments_zelle_qr_data', '')
    Setting.set('payments_zelle_qr_path', '')
    AuditLog.record(current_user.id, 'settings.zelle_qr', 'Removed Zelle QR code')
    db.session.commit()
    return jsonify({'message': 'QR code removed'})


@bp.route('/settings/payments/square-token', methods=['DELETE'])
@login_required
def clear_square_token():
    """Clear the stored Square access token."""
    err = _admin_only()
    if err:
        return err
    Setting.set('payments_square_access_token', '')
    AuditLog.record(current_user.id, 'settings.update', 'Cleared Square access token')
    db.session.commit()
    return jsonify({'message': 'Square access token cleared'})


@bp.route('/settings/payments/test-square', methods=['POST'])
@login_required
def test_square_connection():
    """Test the configured Square credentials against the Square API."""
    err = _admin_only()
    if err:
        return err
    ok, message = square_service.test_connection()
    return jsonify({'ok': ok, 'message': message}), (200 if ok else 400)


@bp.route('/payment-options', methods=['GET'])
@login_required
def get_payment_options():
    """Get enabled payment options for the parent portal (no sensitive data)."""
    options = []
    if Setting.get_bool('payments_zelle_enabled'):
        options.append({
            'type': 'zelle',
            'name': Setting.get('payments_zelle_name', 'Zelle'),
            'qr': Setting.get('payments_zelle_qr_data') or Setting.get('payments_zelle_qr_path', ''),
            'memo': Setting.get('payments_zelle_memo') or DEFAULT_ZELLE_MEMO,
        })
    if Setting.get_bool('payments_cashapp_enabled'):
        tag = Setting.get('payments_cashapp_tag', '').lstrip('$')
        options.append({
            'type': 'cashapp',
            'tag': f'${tag}' if tag else '',
            'cashtag': tag,
            'url': f'https://cash.app/${tag}' if tag else '',
        })
    if Setting.get_bool('payments_square_enabled'):
        options.append({
            'type': 'square',
            'configured': square_service.is_configured(),
        })
    return jsonify({'payment_options': options})


@bp.route('/audit-log', methods=['GET'])
@login_required
def get_audit_log():
    """Recent audit entries (admin only)."""
    err = _admin_only()
    if err:
        return err
    limit = min(request.args.get('limit', 50, type=int), 200)
    rows = AuditLog.query.order_by(desc(AuditLog.created_at)).limit(limit).all()
    return jsonify({'entries': [{
        'id': r.id,
        'action': r.action,
        'detail': r.detail,
        'user': r.user.full_name if r.user else 'System',
        'created_at': r.created_at.isoformat(),
    } for r in rows]})


# ── Pending payment (reconciliation) endpoints ──────────────────────

VALID_PAYMENT_METHODS = {'zelle', 'cashapp', 'square', 'cash', 'venmo', 'other'}
STUDIO_NAME = "LaShelle's School of Dance"


def _parent_student_ids(user) -> set:
    """Set of student ids a parent is linked to."""
    return {s.id for s in user.get_children()} if user.is_parent else set()


def _pending_to_dict(p) -> dict:
    if p.student:
        who = p.student.full_name
    elif p.family:
        who = f'{p.family.name} (family)'
    else:
        who = 'Unknown'
    return {
        'id': p.id,
        'student_id': p.student_id,
        'family_id': p.family_id,
        'who': who,
        'parent_name': p.parent.full_name if p.parent else None,
        'amount': f'{float(p.amount):.2f}',
        'method': p.method,
        'reference': p.reference,
        'note': p.note,
        'status': p.status,
        'admin_note': p.admin_note,
        'created_at': p.created_at.isoformat(),
        'reviewed_at': p.reviewed_at.isoformat() if p.reviewed_at else None,
        'reviewed_by': p.reviewer.full_name if p.reviewer else None,
    }


def _send_receipt(parent_email, who, amount, method):
    """Best-effort payment receipt email. Never raises."""
    if not parent_email:
        return
    from app import email as email_service
    if not email_service.is_configured():
        return
    method_label = {'zelle': 'Zelle', 'cashapp': 'Cash App', 'square': 'Square',
                    'cash': 'cash', 'venmo': 'Venmo'}.get(method, method)
    body = (
        f"Hi,\n\n"
        f"This confirms we've received and recorded your payment of ${amount:.2f} "
        f"for {who} via {method_label}.\n\n"
        f"You can view your balance any time in the parent portal.\n\n"
        f"Thank you,\n{STUDIO_NAME}"
    )
    try:
        email_service.send_email(parent_email, f'Payment received — {STUDIO_NAME}', body)
    except Exception:
        logger.exception("Failed to send payment receipt to %s", parent_email)


@bp.route('/payments/claim', methods=['POST'])
@login_required
def claim_payment():
    """A parent reports a payment they've sent externally (awaits admin confirm)."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    method = (data.get('method') or '').strip().lower()
    if method not in VALID_PAYMENT_METHODS:
        return jsonify({'error': f'Invalid payment method. One of: {", ".join(sorted(VALID_PAYMENT_METHODS))}'}), 400

    try:
        amount = round(float(data.get('amount')), 2)
    except (TypeError, ValueError):
        return jsonify({'error': 'A valid amount is required'}), 400
    if amount <= 0:
        return jsonify({'error': 'Amount must be greater than zero'}), 400

    student_id = data.get('student_id')
    family_id = data.get('family_id')
    if not student_id and not family_id:
        return jsonify({'error': 'student_id or family_id is required'}), 400

    # Authorization: parents may only claim for their own children/families
    if current_user.is_parent:
        my_students = _parent_student_ids(current_user)
        if student_id and int(student_id) not in my_students:
            return jsonify({'error': 'Not authorized for this student'}), 403
        if family_id:
            my_families = {Student.query.get(sid).family_id for sid in my_students}
            if int(family_id) not in my_families:
                return jsonify({'error': 'Not authorized for this family'}), 403
    elif not current_user.is_staff:
        return jsonify({'error': 'Not authorized'}), 403

    p = PendingPayment(
        student_id=int(student_id) if student_id else None,
        family_id=int(family_id) if family_id else None,
        parent_id=current_user.id,
        amount=amount,
        method=method,
        reference=(data.get('reference') or '').strip() or None,
        note=(data.get('note') or '').strip() or None,
    )
    db.session.add(p)
    db.session.commit()

    # Notify admins by email (best-effort)
    from app import email as email_service
    if email_service.is_configured():
        who = p.student.full_name if p.student else (p.family.name + ' (family)' if p.family else 'a family')
        admin_emails = {u.email for u in User.query.filter_by(role='admin', is_active=True).all() if u.email and '@' in u.email}
        if admin_emails:
            try:
                email_service.send_email(
                    admin_emails,
                    f'New payment to confirm — {who}',
                    f'{current_user.full_name} reported a {method} payment of ${amount:.2f} for {who}.\n\n'
                    f'Reference: {p.reference or "(none)"}\n\nConfirm it in the Pending Payments page.',
                )
            except Exception:
                logger.exception("Failed to notify admins of pending payment")

    return jsonify({'message': 'Payment reported — the studio will confirm it shortly.',
                    'pending_payment': _pending_to_dict(p)}), 201


@bp.route('/pending-payments', methods=['GET'])
@login_required
def list_pending_payments():
    err = _admin_only()
    if err:
        return err
    status = request.args.get('status', 'pending').strip()
    query = PendingPayment.query
    if status and status != 'all':
        query = query.filter_by(status=status)
    rows = query.order_by(desc(PendingPayment.created_at)).limit(200).all()
    return jsonify({'pending_payments': [_pending_to_dict(p) for p in rows]})


@bp.route('/pending-payments/count', methods=['GET'])
@login_required
def pending_payments_count():
    if not current_user.is_staff:
        return jsonify({'count': 0})
    return jsonify({'count': PendingPayment.query.filter_by(status='pending').count()})


@bp.route('/pending-payments/<int:pid>/confirm', methods=['POST'])
@login_required
def confirm_pending_payment(pid):
    err = _admin_only()
    if err:
        return err
    p = PendingPayment.query.get_or_404(pid)
    if p.status != 'pending':
        return jsonify({'error': f'Already {p.status}'}), 400

    data = request.get_json(silent=True) or {}
    category = (data.get('category') or 'tuition').strip()
    amount = float(p.amount)

    # Determine per-student allocation
    if p.student_id:
        allocations = [(p.student_id, amount)]
        receipt_email = p.student.parent_email or p.student.email
        who = p.student.full_name
    else:
        students = p.family.students.filter_by(is_active=True).all()
        allocations = allocate_family_payment([s.id for s in students], amount)
        if not allocations:
            # Nobody owed and no students — record against first student if any
            if students:
                allocations = [(students[0].id, amount)]
            else:
                return jsonify({'error': 'Family has no active students to credit'}), 400
        receipt_email = p.family.primary_email or (students[0].parent_email if students else None)
        who = f'{p.family.name} (family)'

    method_label = p.method
    desc_ref = f' (ref: {p.reference})' if p.reference else ''
    first_txn = None
    for sid, portion in allocations:
        t = Transaction(
            student_id=sid,
            type='payment',
            amount=portion,
            category=category,
            payment_method=method_label,
            description=f'Online payment via {method_label}{desc_ref}',
            transaction_date=date.today(),
            created_by=current_user.id,
        )
        db.session.add(t)
        if first_txn is None:
            db.session.flush()
            first_txn = t

    p.status = 'confirmed'
    p.reviewed_at = datetime.utcnow()
    p.reviewed_by = current_user.id
    p.transaction_id = first_txn.id if first_txn else None
    if data.get('admin_note'):
        p.admin_note = data['admin_note'].strip()

    AuditLog.record(current_user.id, 'payment.confirm',
                    f'Confirmed ${amount:.2f} {method_label} for {who}')
    db.session.commit()

    _send_receipt(receipt_email, who, amount, p.method)
    return jsonify({'message': f'Payment of ${amount:.2f} confirmed', 'pending_payment': _pending_to_dict(p)})


@bp.route('/pending-payments/<int:pid>/reject', methods=['POST'])
@login_required
def reject_pending_payment(pid):
    err = _admin_only()
    if err:
        return err
    p = PendingPayment.query.get_or_404(pid)
    if p.status != 'pending':
        return jsonify({'error': f'Already {p.status}'}), 400
    data = request.get_json(silent=True) or {}
    p.status = 'rejected'
    p.admin_note = (data.get('admin_note') or '').strip() or None
    p.reviewed_at = datetime.utcnow()
    p.reviewed_by = current_user.id
    who = p.student.full_name if p.student else (p.family.name + ' (family)' if p.family else 'unknown')
    AuditLog.record(current_user.id, 'payment.reject',
                    f'Rejected ${float(p.amount):.2f} {p.method} for {who}')
    db.session.commit()
    return jsonify({'message': 'Payment claim rejected', 'pending_payment': _pending_to_dict(p)})


@bp.route('/my-payments', methods=['GET'])
@login_required
def my_payments():
    """A parent's own pending claims + recent confirmed payments across children."""
    if not current_user.is_parent:
        return jsonify({'pending': [], 'history': []})

    student_ids = list(_parent_student_ids(current_user))
    pending = (PendingPayment.query
               .filter_by(parent_id=current_user.id)
               .order_by(desc(PendingPayment.created_at)).limit(50).all())

    history = []
    if student_ids:
        txns = (Transaction.query
                .filter(Transaction.student_id.in_(student_ids), Transaction.type == 'payment')
                .order_by(desc(Transaction.transaction_date), desc(Transaction.created_at))
                .limit(50).all())
        history = [transaction_to_dict(t) for t in txns]

    return jsonify({
        'pending': [_pending_to_dict(p) for p in pending],
        'history': history,
    })


# ── Balance reminder emails ─────────────────────────────────────────

def _reminder_body(name, balance):
    return (
        f"Hi,\n\n"
        f"This is a friendly reminder that {name} has an outstanding balance of "
        f"${balance:.2f} with {STUDIO_NAME}.\n\n"
        f"You can pay any time through the parent portal. Thank you!\n\n"
        f"{STUDIO_NAME}"
    )


@bp.route('/balances/send-reminders', methods=['POST'])
@login_required
def send_balance_reminders():
    """Email every student with an outstanding balance a reminder."""
    err = _admin_only()
    if err:
        return err
    from app import email as email_service
    if not email_service.is_configured():
        return jsonify({'error': 'Email (SMTP) is not configured'}), 400

    students = Student.query.filter_by(is_active=True).all()
    balances = calc_balance_bulk([s.id for s in students])
    sent, skipped = 0, 0
    for s in students:
        bal = balances[s.id]['balance']
        if bal <= 0:
            continue
        to = s.parent_email or s.email
        if not to:
            skipped += 1
            continue
        try:
            email_service.send_email(to, f'Balance reminder — {STUDIO_NAME}',
                                     _reminder_body(s.full_name, bal))
            sent += 1
        except Exception:
            logger.exception("Failed to send reminder for %s", s.full_name)
            skipped += 1

    AuditLog.record(current_user.id, 'reminders.send', f'Sent {sent} balance reminders ({skipped} skipped)')
    db.session.commit()
    return jsonify({'message': f'Sent {sent} reminder(s), skipped {skipped}', 'sent': sent, 'skipped': skipped})


@bp.route('/students/<int:student_id>/send-reminder', methods=['POST'])
@login_required
def send_student_reminder(student_id):
    err = _admin_only()
    if err:
        return err
    from app import email as email_service
    if not email_service.is_configured():
        return jsonify({'error': 'Email (SMTP) is not configured'}), 400
    student = Student.query.get_or_404(student_id)
    bal = calc_balance(student_id)['balance']
    if bal <= 0:
        return jsonify({'error': 'No outstanding balance'}), 400
    to = student.parent_email or student.email
    if not to:
        return jsonify({'error': 'No email on file for this student'}), 400
    try:
        email_service.send_email(to, f'Balance reminder — {STUDIO_NAME}',
                                 _reminder_body(student.full_name, bal))
    except Exception as e:
        return jsonify({'error': f'Send failed: {e}'}), 500
    AuditLog.record(current_user.id, 'reminders.send', f'Sent reminder to {student.full_name}')
    db.session.commit()
    return jsonify({'message': f'Reminder sent to {to}'})


# ── Square webhook (auto-reconcile online invoice payments) ──────────

@bp.route('/webhooks/square', methods=['POST'])
def square_webhook():
    """Receive Square invoice payment events and auto-record the payment.

    No login (Square calls this). Verified via HMAC signature when a signature
    key is configured.
    """
    import base64
    import hashlib
    import hmac
    import json

    raw_body = request.get_data()

    # Verify signature if a key is configured
    from app.crypto import decrypt
    sig_key = decrypt(Setting.get('payments_square_webhook_signature_key', ''))
    if sig_key:
        provided = request.headers.get('x-square-hmacsha256-signature', '')
        mac = hmac.new(sig_key.encode('utf-8'), (request.url + raw_body.decode('utf-8')).encode('utf-8'),
                       hashlib.sha256)
        expected = base64.b64encode(mac.digest()).decode('ascii')
        if not hmac.compare_digest(expected, provided):
            logger.warning("Square webhook signature mismatch")
            return jsonify({'error': 'Invalid signature'}), 403
    else:
        logger.warning("Square webhook received but no signature key configured — skipping verification")

    try:
        event = json.loads(raw_body or b'{}')
    except ValueError:
        return jsonify({'error': 'Invalid JSON'}), 400

    event_type = event.get('type', '')
    invoice = (event.get('data', {}).get('object', {}) or {}).get('invoice', {})
    invoice_id = invoice.get('id')
    status = invoice.get('status', '')

    if not invoice_id or status not in ('PAID', 'PARTIALLY_PAID'):
        return jsonify({'status': 'ignored'}), 200

    rec = SquareInvoice.query.filter_by(invoice_id=invoice_id).first()
    if not rec:
        logger.info("Square webhook for unknown invoice %s", invoice_id)
        return jsonify({'status': 'unknown_invoice'}), 200
    if rec.paid_at:
        return jsonify({'status': 'already_recorded'}), 200

    student = Student.query.get(rec.student_id)
    if not student:
        return jsonify({'status': 'unknown_student'}), 200

    amount = rec.amount_cents / 100.0
    t = Transaction(
        student_id=student.id,
        type='payment',
        amount=amount,
        category='tuition',
        payment_method='square',
        description=f'Square invoice {invoice_id} ({event_type})',
        transaction_date=date.today(),
        created_by=None,
    )
    db.session.add(t)
    rec.status = status
    rec.paid_at = datetime.utcnow()
    AuditLog.record(None, 'payment.square_webhook',
                    f'Auto-recorded ${amount:.2f} for {student.full_name} (invoice {invoice_id})')
    db.session.commit()

    _send_receipt(student.parent_email or student.email, student.full_name, amount, 'square')
    return jsonify({'status': 'recorded'}), 200
