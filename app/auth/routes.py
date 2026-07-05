"""Authentication routes for AttenDANCE system."""

from datetime import datetime

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from urllib.parse import urlparse

from app import db
from app.auth import bp
from app.models import ParentStudent, Student, User


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

        # Accept username OR email. Invited parents get an auto-generated
        # `parent-<code>` username they never see, and they register with an
        # email — so email login is the only way they can get back in after
        # logging out. Email is unique, so the match is unambiguous.
        user = User.query.filter_by(username=username).first()
        if user is None and '@' in username:
            user = User.query.filter_by(email=username).first()

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

        # If this email already belongs to an active account, don't create a
        # duplicate. Sibling families get one invite per child, so the second+
        # invite should ADD the dancer to the parent's existing login rather
        # than 500 on the unique-email constraint or split kids across accounts.
        existing = User.query.filter(User.email == email, User.is_active == True,  # noqa: E712
                                     User.id != invite_user.id).first()
        if existing:
            if not existing.is_parent:
                flash('That email is already in use. Please use a different email.', 'error')
                return render_template('auth/register.html')
            # Move the invited dancer(s) onto the existing parent account, then
            # drop the redundant invite account. Use bulk queries (not ORM object
            # mutation) so deleting the invite user can't cascade-null the moved
            # links; commit the move before the delete.
            existing_links = {ps.student_id for ps in
                              ParentStudent.query.filter_by(parent_id=existing.id).all()}
            if existing_links:
                ParentStudent.query.filter(
                    ParentStudent.parent_id == invite_user.id,
                    ParentStudent.student_id.in_(existing_links),
                ).delete(synchronize_session=False)
            ParentStudent.query.filter_by(parent_id=invite_user.id).update(
                {'parent_id': existing.id}, synchronize_session=False)
            db.session.commit()
            db.session.delete(invite_user)
            db.session.commit()
            flash('This dancer was added to your existing account — please log in.', 'success')
            return redirect(url_for('auth.login'))

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


def _reset_serializer():
    from flask import current_app
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='password-reset')


@bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Request a password reset. Emails a signed, 1-hour link if email is
    configured; otherwise tells the user to contact the studio. Always shows a
    generic message so it can't be used to enumerate which emails have accounts."""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    if request.method == 'POST':
        from app import email as email_service
        email = request.form.get('email', '').strip()
        if not email_service.is_configured():
            flash("Email isn't set up yet — please contact the studio at "
                  "LaShellesDance@gmail.com to reset your password.", 'info')
            return render_template('auth/forgot_password.html')
        user = User.query.filter_by(email=email, is_active=True).first()
        if user:
            token = _reset_serializer().dumps(user.id)
            link = url_for('auth.reset_password', token=token, _external=True)
            body = (f"Hi {user.first_name},\n\nSomeone requested a password reset for your "
                    f"LaShelle's School of Dance account. Use the link below to set a new "
                    f"password (it expires in 1 hour):\n\n{link}\n\n"
                    f"If you didn't request this, you can ignore this email.\n")
            try:
                email_service.send_email(email, "Reset your password — LaShelle's School of Dance", body)
            except Exception:
                pass  # generic response regardless; don't leak send failures
        flash("If an account exists for that email, a reset link is on its way.", 'success')
        return render_template('auth/forgot_password.html')
    return render_template('auth/forgot_password.html')


@bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """Complete a password reset from a signed, time-limited token."""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    from itsdangerous import BadSignature, SignatureExpired
    try:
        user_id = _reset_serializer().loads(token, max_age=3600)
    except SignatureExpired:
        flash('That reset link has expired — please request a new one.', 'error')
        return redirect(url_for('auth.forgot_password'))
    except BadSignature:
        flash('That reset link is invalid.', 'error')
        return redirect(url_for('auth.forgot_password'))
    user = User.query.get(user_id)
    if not user or not user.is_active:
        flash('That reset link is invalid.', 'error')
        return redirect(url_for('auth.forgot_password'))
    if request.method == 'POST':
        pw = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        if len(pw) < 6:
            flash('Password must be at least 6 characters.', 'error')
            return render_template('auth/reset_password.html', token=token)
        if pw != confirm:
            flash('Passwords do not match.', 'error')
            return render_template('auth/reset_password.html', token=token)
        user.set_password(pw)
        db.session.commit()
        flash('Password updated — please log in with your new password.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/reset_password.html', token=token, user=user)
