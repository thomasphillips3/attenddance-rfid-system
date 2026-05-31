"""
Main web interface routes for AttenDANCE system
"""

from datetime import date, datetime, timedelta
from flask import render_template, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func, desc
from app.main import bp
from app import db
from app.models import Student, DanceClass, Attendance, RFIDLog

@bp.route('/')
def index():
    """Home page - redirect to login or dashboard"""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('auth.login'))

@bp.route('/dashboard')
@login_required
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
@login_required
def students():
    """Students list page"""
    return render_template('students/list.html')

@bp.route('/classes')
@login_required
def classes():
    """Classes list page"""
    return render_template('classes/list.html')

@bp.route('/attendance')
@login_required
def attendance():
    """Attendance list page"""
    return render_template('attendance/list.html') 