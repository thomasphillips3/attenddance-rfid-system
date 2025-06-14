"""
Main web interface routes for AttenDANCE system
"""

from flask import render_template, redirect, url_for
from flask_login import login_required, current_user
from app.main import bp

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
    return render_template('dashboard.html')

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