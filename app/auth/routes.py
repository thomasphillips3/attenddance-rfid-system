"""Authentication routes for AttenDANCE system."""

from datetime import datetime

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from urllib.parse import urlparse

from app import db
from app.auth import bp
from app.models import Student, User


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        if request.is_json:
            data = request.get_json()
            username = data.get('username', '').strip()
            password = data.get('password', '')
            remember_me = data.get('remember_me', False)
        else:
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            remember_me = bool(request.form.get('remember_me'))

        if not username or not password:
            error_msg = 'Username and password are required'
            if request.is_json:
                return jsonify({'success': False, 'message': error_msg}), 400
            flash(error_msg, 'error')
            return render_template('auth/login.html')

        user = User.query.filter_by(username=username).first()

        if user is None or not user.check_password(password):
            error_msg = 'Invalid username or password'
            if request.is_json:
                return jsonify({'success': False, 'message': error_msg}), 401
            flash(error_msg, 'error')
            return render_template('auth/login.html')

        if not user.is_active:
            error_msg = 'Account is disabled'
            if request.is_json:
                return jsonify({'success': False, 'message': error_msg}), 401
            flash(error_msg, 'error')
            return render_template('auth/login.html')

        login_user(user, remember=remember_me)
        user.last_login = datetime.utcnow()
        db.session.commit()

        next_page = request.args.get('next')
        if not next_page or urlparse(next_page).netloc != '':
            if user.is_parent:
                next_page = url_for('main.parent_dashboard')
            else:
                next_page = url_for('main.dashboard')

        if request.is_json:
            return jsonify({
                'success': True,
                'message': f'Welcome back, {user.first_name}!',
                'redirect': next_page,
            })

        flash(f'Welcome back, {user.first_name}!', 'success')
        return redirect(next_page)

    return render_template('auth/login.html')


@bp.route('/logout')
@login_required
def logout():
    user_name = current_user.first_name
    logout_user()

    if request.is_json:
        return jsonify({'success': True, 'message': f'Goodbye, {user_name}!'})

    flash(f'Goodbye, {user_name}!', 'info')
    return redirect(url_for('auth.login'))


@bp.route('/profile')
@login_required
def profile():
    return render_template('auth/profile.html', user=current_user)


@bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        if request.is_json:
            data = request.get_json()
            current_password = data.get('current_password', '')
            new_password = data.get('new_password', '')
            confirm_password = data.get('confirm_password', '')
        else:
            current_password = request.form.get('current_password', '')
            new_password = request.form.get('new_password', '')
            confirm_password = request.form.get('confirm_password', '')

        if not current_user.check_password(current_password):
            error_msg = 'Current password is incorrect'
            if request.is_json:
                return jsonify({'success': False, 'message': error_msg}), 400
            flash(error_msg, 'error')
            return render_template('auth/change_password.html')

        if len(new_password) < 6:
            error_msg = 'New password must be at least 6 characters long'
            if request.is_json:
                return jsonify({'success': False, 'message': error_msg}), 400
            flash(error_msg, 'error')
            return render_template('auth/change_password.html')

        if new_password != confirm_password:
            error_msg = 'New passwords do not match'
            if request.is_json:
                return jsonify({'success': False, 'message': error_msg}), 400
            flash(error_msg, 'error')
            return render_template('auth/change_password.html')

        current_user.set_password(new_password)
        db.session.commit()

        success_msg = 'Password updated successfully'
        if request.is_json:
            return jsonify({'success': True, 'message': success_msg})

        flash(success_msg, 'success')
        return redirect(url_for('auth.profile'))

    return render_template('auth/change_password.html')


@bp.route('/check-session')
def check_session():
    if current_user.is_authenticated:
        return jsonify({
            'authenticated': True,
            'username': current_user.username,
            'full_name': current_user.full_name,
            'is_admin': current_user.is_admin,
        })
    return jsonify({'authenticated': False}), 401


@bp.route('/register', methods=['GET', 'POST'])
def register_parent():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        invite_code = request.form.get('invite_code', '').strip()
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        if not all([invite_code, first_name, last_name, email, password]):
            flash('All fields are required', 'error')
            return render_template('auth/register.html')

        invite_user = User.query.filter_by(invite_code=invite_code, role='parent', is_active=False).first()
        if not invite_user:
            flash('Invalid invite code', 'error')
            return render_template('auth/register.html')

        invite_user.first_name = first_name
        invite_user.last_name = last_name
        invite_user.email = email
        invite_user.set_password(password)
        invite_user.is_active = True
        invite_user.invite_code = None
        db.session.commit()

        login_user(invite_user)
        flash(f'Welcome, {first_name}!', 'success')
        return redirect(url_for('main.parent_dashboard'))

    return render_template('auth/register.html')
