"""Main web interface routes for AttenDANCE system."""

from datetime import date, timedelta
from functools import wraps

from flask import redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy import desc, func

from app import db
from app.helpers import calc_balance
from app.main import bp
from app.models import (
    Attendance,
    ClassEnrollment,
    DanceClass,
    Family,
    Student,
    Transaction,
)


def staff_required(f):
    """Decorator: only admin/teacher can access."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.is_parent:
            return redirect(url_for('main.parent_dashboard'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Decorator: only admin can access."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated


@bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('auth.login'))


@bp.route('/dashboard')
@staff_required
def dashboard():
    today = date.today()
    current_weekday = today.weekday()

    total_students = Student.query.filter_by(is_active=True).count()
    total_classes = DanceClass.query.filter_by(is_active=True).count()
    todays_attendance = Attendance.query.filter(
        func.date(Attendance.check_in_time) == today
    ).count()
    students_without_rfid = Student.query.filter_by(
        is_active=True, rfid_uid=None
    ).count()

    todays_classes = DanceClass.query.filter_by(
        is_active=True, day_of_week=current_weekday
    ).order_by(DanceClass.start_time).all()

    from app.models import RFIDLog
    recent_attendance = Attendance.query.order_by(
        desc(Attendance.check_in_time)
    ).limit(10).all()
    recent_rfid_logs = RFIDLog.query.order_by(
        desc(RFIDLog.scan_time)
    ).limit(10).all()

    return render_template('dashboard.html',
        today=today,
        total_students=total_students,
        total_classes=total_classes,
        todays_attendance=todays_attendance,
        students_without_rfid=students_without_rfid,
        todays_classes=todays_classes,
        recent_attendance=recent_attendance,
        recent_rfid_logs=recent_rfid_logs,
    )


@bp.route('/students')
@staff_required
def students():
    return render_template('students/list.html')


@bp.route('/classes')
@staff_required
def classes():
    return render_template('classes/list.html')


@bp.route('/attendance')
@staff_required
def attendance():
    return render_template('attendance/list.html')


@bp.route('/parent')
@login_required
def parent_dashboard():
    if not current_user.is_parent:
        return redirect(url_for('main.dashboard'))
    children = current_user.get_children()
    child_data = []
    family_groups = {}  # family_id -> {name, balance, member_ids, member_names}
    for child in children:
        bal = calc_balance(child.id)
        recent_att = Attendance.query.filter_by(student_id=child.id).order_by(
            desc(Attendance.check_in_time)).limit(10).all()
        child_data.append({
            'student': child,
            'balance': bal['balance'],
            'total_charges': bal['total_charges'],
            'total_payments': bal['total_payments'],
            'recent_attendance': recent_att,
        })
        if child.family_id:
            g = family_groups.setdefault(child.family_id, {
                'family_id': child.family_id,
                'name': child.family.name if child.family else 'Family',
                'balance': 0.0,
                'members': [],
            })
            g['balance'] += bal['balance']
            g['members'].append(child.full_name)

    # Only offer combined pay when a family has 2+ of this parent's children and owes money
    families = [g for g in family_groups.values() if len(g['members']) > 1 and g['balance'] > 0]
    return render_template('parent/dashboard.html', children=child_data, families=families)


@bp.route('/transactions')
@staff_required
def transactions():
    students = Student.query.filter_by(is_active=True).order_by(Student.last_name, Student.first_name).all()
    classes = DanceClass.query.filter_by(is_active=True).order_by(DanceClass.name).all()
    return render_template('transactions/list.html', students=students, classes=classes)


@bp.route('/students/<int:student_id>/detail')
@staff_required
def student_detail(student_id):
    student = Student.query.get_or_404(student_id)
    enrollments = ClassEnrollment.query.filter_by(student_id=student_id, is_active=True).all()
    classes = [e.dance_class for e in enrollments if e.dance_class]
    bal = calc_balance(student_id)
    recent_att = Attendance.query.filter_by(student_id=student_id).order_by(
        desc(Attendance.check_in_time)).limit(10).all()
    return render_template('students/detail.html', student=student, classes=classes,
        balance=bal['balance'], total_charges=bal['total_charges'],
        total_payments=bal['total_payments'], recent_attendance=recent_att)


@bp.route('/students/<int:student_id>/ledger')
@login_required
def student_ledger(student_id):
    student = Student.query.get_or_404(student_id)
    return render_template('transactions/ledger.html', student=student)


@bp.route('/families')
@staff_required
def families_page():
    return render_template('families/list.html')


@bp.route('/families/<int:family_id>/ledger')
@staff_required
def family_ledger(family_id):
    family = Family.query.get_or_404(family_id)
    return render_template('families/ledger.html', family=family)


@bp.route('/messages')
@staff_required
def messages_page():
    students = Student.query.filter_by(is_active=True).order_by(Student.last_name).all()
    classes = DanceClass.query.filter_by(is_active=True).order_by(DanceClass.name).all()
    return render_template('messages/list.html', students=students, classes=classes)


@bp.route('/rules')
@staff_required
def rules_admin():
    students = Student.query.filter_by(is_active=True).order_by(Student.last_name).all()
    return render_template('rules/admin.html', students=students)


@bp.route('/rules/acknowledge/<int:student_id>')
@login_required
def acknowledge_rules(student_id):
    student = Student.query.get_or_404(student_id)
    return render_template('rules/acknowledge.html', student=student)


@bp.route('/take-attendance')
@login_required
def take_attendance():
    today = date.today()
    current_weekday = today.weekday()
    todays_classes = DanceClass.query.filter_by(
        is_active=True, day_of_week=current_weekday
    ).order_by(DanceClass.start_time).all()
    all_classes = DanceClass.query.filter_by(is_active=True).order_by(
        DanceClass.day_of_week, DanceClass.start_time
    ).all()
    return render_template('attendance/take_pick.html',
        today=today, todays_classes=todays_classes, all_classes=all_classes)


@bp.route('/take-attendance/<int:class_id>')
@login_required
def take_attendance_class(class_id):
    """Card-based attendance for a class — prefetches all data in bulk."""
    dance_class = DanceClass.query.get_or_404(class_id)
    today = date.today()

    # Get 8 weeks of dates (current week + 7 prior)
    current_monday = today - timedelta(days=today.weekday())
    weeks = [(current_monday - timedelta(weeks=i)) for i in range(7, -1, -1)]
    earliest = weeks[0]
    latest = weeks[-1] + timedelta(days=6)

    # Bulk-load enrolled students
    enrollments = (
        ClassEnrollment.query
        .filter_by(class_id=class_id, is_active=True)
        .all()
    )
    student_ids = [e.student_id for e in enrollments]
    if not student_ids:
        return render_template('attendance/take.html',
            dance_class=dance_class, students=[], weeks=weeks,
            today=today, current_monday=current_monday, today_checked={})

    enrolled_students = Student.query.filter(Student.id.in_(student_ids)).all()
    student_map = {s.id: s for s in enrolled_students}

    # Prefetch ALL attendance for these students in this class across the 8-week window
    all_attendance = Attendance.query.filter(
        Attendance.student_id.in_(student_ids),
        Attendance.class_id == class_id,
        func.date(Attendance.check_in_time) >= earliest,
        func.date(Attendance.check_in_time) <= latest,
    ).all()

    # Build lookup: (student_id, week_start_iso) -> bool
    att_lookup = {}
    today_checked = {}
    for att in all_attendance:
        att_date = att.check_in_time.date()
        att_monday = att_date - timedelta(days=att_date.weekday())
        key = (att.student_id, att_monday.isoformat())
        att_lookup[key] = True
        if att_date == today:
            today_checked[att.student_id] = True

    students = []
    for sid in student_ids:
        s = student_map.get(sid)
        if not s:
            continue
        week_marks = {}
        for week_start in weeks:
            week_marks[week_start.isoformat()] = (sid, week_start.isoformat()) in att_lookup
        students.append({
            'id': s.id,
            'full_name': s.full_name,
            'first_name': s.first_name,
            'weeks': week_marks,
        })
    students.sort(key=lambda x: x['full_name'])

    # Fill in False for students not in today_checked
    for s in students:
        if s['id'] not in today_checked:
            today_checked[s['id']] = False

    return render_template('attendance/take.html',
        dance_class=dance_class, students=students,
        weeks=weeks, today=today, current_monday=current_monday,
        today_checked=today_checked)


@bp.route('/staff')
@admin_required
def staff_page():
    """Staff/teacher management page (admin only)."""
    return render_template('staff/list.html')


@bp.route('/locations')
@admin_required
def locations_page():
    return render_template('locations/list.html')


@bp.route('/settings')
@admin_required
def settings_page():
    return render_template('settings/payments.html')


@bp.route('/pending-payments')
@admin_required
def pending_payments_page():
    return render_template('payments/pending.html')
