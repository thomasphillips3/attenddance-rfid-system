"""
Main web interface routes for AttenDANCE system
"""

from datetime import date, datetime, timedelta
from functools import wraps
from flask import render_template, redirect, url_for, abort
from flask_login import login_required, current_user
from sqlalchemy import func, desc
from app.main import bp
from app import db
from app.models import Student, DanceClass, ClassEnrollment, Attendance, RFIDLog, Transaction, ParentStudent, Rule

def staff_required(f):
    """Decorator: only admin/teacher can access."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if (current_user.role or 'teacher') == 'parent':
            return redirect(url_for('main.parent_dashboard'))
        return f(*args, **kwargs)
    return decorated

@bp.route('/')
def index():
    """Home page - redirect to login or dashboard"""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('auth.login'))

@bp.route('/dashboard')
@staff_required
def dashboard():
    """Main dashboard"""
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
    """Students list page"""
    return render_template('students/list.html')

@bp.route('/classes')
@staff_required
def classes():
    """Classes list page"""
    return render_template('classes/list.html')

@bp.route('/attendance')
@staff_required
def attendance():
    """Attendance list page"""
    return render_template('attendance/list.html')

@bp.route('/parent')
@login_required
def parent_dashboard():
    """Parent dashboard — read-only view of their children"""
    if (current_user.role or 'teacher') != 'parent':
        return redirect(url_for('main.dashboard'))
    children = current_user.get_children()
    child_data = []
    for child in children:
        txns = Transaction.query.filter_by(student_id=child.id).all()
        total_charges = sum(float(t.amount) for t in txns if (t.type or 'payment') == 'charge')
        total_payments = sum(float(t.amount) for t in txns if (t.type or 'payment') == 'payment')
        recent_att = Attendance.query.filter_by(student_id=child.id).order_by(
            desc(Attendance.check_in_time)).limit(10).all()
        child_data.append({
            'student': child,
            'balance': total_charges - total_payments,
            'total_charges': total_charges,
            'total_payments': total_payments,
            'recent_attendance': recent_att,
        })
    return render_template('parent/dashboard.html', children=child_data)

@bp.route('/transactions')
@staff_required
def transactions():
    """Transactions page"""
    students = Student.query.filter_by(is_active=True).order_by(Student.last_name, Student.first_name).all()
    classes = DanceClass.query.filter_by(is_active=True).order_by(DanceClass.name).all()
    return render_template('transactions/list.html', students=students, classes=classes)

@bp.route('/students/<int:student_id>/ledger')
@login_required
def student_ledger(student_id):
    """Per-student ledger page"""
    student = Student.query.get_or_404(student_id)
    return render_template('transactions/ledger.html', student=student)

@bp.route('/messages')
@staff_required
def messages_page():
    """Email blast page"""
    students = Student.query.filter_by(is_active=True).order_by(Student.last_name).all()
    classes = DanceClass.query.filter_by(is_active=True).order_by(DanceClass.name).all()
    return render_template('messages/list.html', students=students, classes=classes)

@bp.route('/rules')
@staff_required
def rules_admin():
    """Admin: manage studio rules"""
    students = Student.query.filter_by(is_active=True).order_by(Student.last_name).all()
    return render_template('rules/admin.html', students=students)

@bp.route('/rules/acknowledge/<int:student_id>')
@login_required
def acknowledge_rules(student_id):
    """Parent: acknowledge rules for a student"""
    student = Student.query.get_or_404(student_id)
    return render_template('rules/acknowledge.html', student=student)

@bp.route('/take-attendance')
@login_required
def take_attendance():
    """Pick a class to take attendance for"""
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
    """Card-based attendance for a class"""
    dance_class = DanceClass.query.get_or_404(class_id)
    enrollments = ClassEnrollment.query.filter_by(
        class_id=class_id, is_active=True
    ).all()
    students = []
    today = date.today()
    # Get 8 weeks of dates (current week + 7 prior)
    current_monday = today - timedelta(days=today.weekday())
    weeks = [(current_monday - timedelta(weeks=i)) for i in range(7, -1, -1)]

    for e in enrollments:
        s = Student.query.get(e.student_id)
        if not s:
            continue
        # Get attendance for these 8 weeks
        week_marks = {}
        for week_start in weeks:
            week_end = week_start + timedelta(days=6)
            att = Attendance.query.filter(
                Attendance.student_id == s.id,
                Attendance.class_id == class_id,
                func.date(Attendance.check_in_time) >= week_start,
                func.date(Attendance.check_in_time) <= week_end,
            ).first()
            week_marks[week_start.isoformat()] = att is not None
        students.append({
            'id': s.id,
            'full_name': s.full_name,
            'first_name': s.first_name,
            'weeks': week_marks,
        })
    students.sort(key=lambda x: x['full_name'])

    # Check if today is already marked
    today_checked = {}
    for s in students:
        att = Attendance.query.filter(
            Attendance.student_id == s['id'],
            Attendance.class_id == class_id,
            func.date(Attendance.check_in_time) == today,
        ).first()
        today_checked[s['id']] = att is not None

    return render_template('attendance/take.html',
        dance_class=dance_class, students=students,
        weeks=weeks, today=today, current_monday=current_monday,
        today_checked=today_checked) 