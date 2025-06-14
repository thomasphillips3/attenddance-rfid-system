"""
Authentication routes for AttenDANCE system
"""

from datetime import datetime
from flask import render_template, flash, redirect, url_for, request, jsonify, session
from flask_login import login_user, logout_user, current_user, login_required
from werkzeug.urls import url_parse

from app.auth import bp
from app.models import User
from app import db

@bp.route('/login', methods=['GET', 'POST'])
def login():
    """Teacher login page"""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        # Handle JSON API requests
        if request.is_json:
            data = request.get_json()
            username = data.get('username', '').strip()
            password = data.get('password', '')
            remember_me = data.get('remember_me', False)
        else:
            # Handle form submissions
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            remember_me = bool(request.form.get('remember_me'))
        
        if not username or not password:
            error_msg = 'Username and password are required'
            if request.is_json:
                return jsonify({'success': False, 'message': error_msg}), 400
            flash(error_msg, 'error')
            return render_template('auth/login.html')
        
        # Find user
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
        
        # Login successful
        login_user(user, remember=remember_me)
        
        # Update last login time
        user.last_login = datetime.utcnow()
        db.session.commit()
        
        # Handle next page redirect
        next_page = request.args.get('next')
        if not next_page or url_parse(next_page).netloc != '':
            next_page = url_for('main.dashboard')
        
        if request.is_json:
            return jsonify({
                'success': True, 
                'message': f'Welcome back, {user.first_name}!',
                'redirect': next_page
            })
        
        flash(f'Welcome back, {user.first_name}!', 'success')
        return redirect(next_page)
    
    return render_template('auth/login.html')

@bp.route('/logout')
@login_required
def logout():
    """Logout current user"""
    user_name = current_user.first_name
    logout_user()
    
    if request.is_json:
        return jsonify({'success': True, 'message': f'Goodbye, {user_name}!'})
    
    flash(f'Goodbye, {user_name}!', 'info')
    return redirect(url_for('auth.login'))

@bp.route('/profile')
@login_required
def profile():
    """User profile page"""
    return render_template('auth/profile.html', user=current_user)

@bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Change user password"""
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
        
        # Validate current password
        if not current_user.check_password(current_password):
            error_msg = 'Current password is incorrect'
            if request.is_json:
                return jsonify({'success': False, 'message': error_msg}), 400
            flash(error_msg, 'error')
            return render_template('auth/change_password.html')
        
        # Validate new password
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
        
        # Update password
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
    """Check if user session is valid (API endpoint)"""
    if current_user.is_authenticated:
        return jsonify({
            'authenticated': True,
            'username': current_user.username,
            'full_name': current_user.full_name,
            'is_admin': current_user.is_admin
        })
    else:
        return jsonify({'authenticated': False}), 401 