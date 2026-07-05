"""Flask application factory for AttenDANCE system."""

import logging
import os

from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

from config.config import config

logger = logging.getLogger(__name__)

db = SQLAlchemy()
login_manager = LoginManager()


def _process_recurring_charges():
    """Create charge transactions for any recurring charges due this month."""
    import calendar
    from datetime import date

    from app.models import ClassEnrollment, RecurringCharge, Transaction

    today = date.today()
    month_start = today.replace(day=1)
    last_day = calendar.monthrange(today.year, today.month)[1]
    actives = RecurringCharge.query.filter_by(is_active=True).all()

    for rc in actives:
        # Clamp the due day to the current month's length so a charge set for the
        # 29th/30th/31st still fires (on the last day) in shorter months instead
        # of being silently skipped — otherwise the studio loses that tuition.
        due_day = min(rc.day_of_month, last_day)
        if today.day < due_day:
            continue
        already = Transaction.query.filter_by(
            recurring_charge_id=rc.id,
        ).filter(Transaction.transaction_date >= month_start).first()
        if already:
            continue
        enrollments = ClassEnrollment.query.filter_by(
            class_id=rc.class_id, is_active=True
        ).all()
        charge_date = today.replace(day=due_day)
        class_name = rc.dance_class.name if rc.dance_class else 'class'
        for e in enrollments:
            t = Transaction(
                student_id=e.student_id,
                type='charge',
                amount=rc.amount,
                category=rc.category,
                payment_method='n/a',
                description=rc.description or f'{class_name} - {rc.category}',
                transaction_date=charge_date,
                recurring_charge_id=rc.id,
                created_by=rc.created_by,
            )
            db.session.add(t)
        logger.info(
            "Recurring charge #%d: charged %d students $%s for %s",
            rc.id, len(enrollments), rc.amount, class_name,
        )

    db.session.commit()


def _process_auto_reminders():
    """Send balance reminders if today matches the configured day and we haven't
    already run this month. Driven by Settings (admin-configurable)."""
    from datetime import date

    from app import email as email_service
    from app import sms as sms_service
    from app.helpers import calc_balance_bulk
    from app.models import Setting, Student

    if not Setting.get_bool('reminders_auto_enabled'):
        return
    today = date.today()
    try:
        day = int(Setting.get('reminders_day_of_month', '1') or 1)
    except ValueError:
        day = 1
    if today.day != day:
        return
    ym = today.strftime('%Y-%m')
    if Setting.get('reminders_last_run', '') == ym:
        return  # already ran this month

    try:
        min_bal = float(Setting.get('reminders_min_balance', '0') or 0)
    except ValueError:
        min_bal = 0.0
    send_sms_too = Setting.get_bool('reminders_send_sms')

    # Mark the month done BEFORE sending. Reminders are a best-effort monthly
    # nudge, and the machine wakes/sleeps all day — if we marked done only at the
    # end, a mid-loop kill (OOM) or an unhandled send error would re-run and
    # re-notify families already reminded (spam). At-most-once beats guaranteed
    # delivery here: the studio still sees unpaid balances on the aging report.
    Setting.set('reminders_last_run', ym)

    students = Student.query.filter_by(is_active=True).all()
    balances = calc_balance_bulk([s.id for s in students])
    email_ok = email_service.is_configured()
    sms_ok = send_sms_too and sms_service.is_configured()
    sent = 0
    for s in students:
        bal = balances[s.id]['balance']
        if bal <= max(0.0, min_bal):
            continue
        body = (f"Hi, this is a friendly reminder that {s.full_name} has a balance of "
                f"${bal:.2f} with LaShelle's School of Dance. You can pay any time in the "
                f"parent portal. Thank you!")
        if email_ok:
            to = s.parent_email or s.email
            if to:
                try:
                    email_service.send_email(to, "Balance reminder — LaShelle's School of Dance", body)
                    sent += 1
                except Exception:
                    logger.exception("Auto-reminder email failed for %s", s.full_name)
        if sms_ok:
            phone = s.parent_phone or (s.family.primary_phone if s.family else None) or s.phone
            if phone:
                try:  # a single SMS failure must not abort the whole run
                    sms_service.send_sms(phone, body)
                except Exception:
                    logger.exception("Auto-reminder SMS failed for %s", s.full_name)

    logger.info("Auto-reminders processed: %d students notified", sent)


def create_app(config_name=None):
    """Application factory function."""
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Fail closed: never run production on a missing or known-default SECRET_KEY.
    # SECRET_KEY signs session cookies AND derives the Fernet key that encrypts
    # the Square token at rest (app/crypto.py), so a guessable value means full
    # admin-session forgery + secret decryption. Set a real one before deploy:
    #   fly secrets set SECRET_KEY=$(python3 -c 'import secrets;print(secrets.token_hex(32))')
    if config_name == 'production':
        sk = app.config.get('SECRET_KEY') or ''
        weak = {
            'dev-secret-key-change-in-production-12345',
            'fly-demo-key-change-for-real-prod',
        }
        if sk in weak or len(sk) < 32:
            raise RuntimeError(
                'Refusing to start in production with a missing or default '
                'SECRET_KEY. Set a strong secret (>=32 chars) via '
                "`fly secrets set SECRET_KEY=...` before deploying."
            )

    db.init_app(app)
    login_manager.init_app(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'

    @login_manager.user_loader
    def load_user(user_id):
        from app.models import User
        return db.session.get(User, int(user_id))

    # Register blueprints
    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from app.api import bp as api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    from app.main import bp as main_bp
    app.register_blueprint(main_bp)

    with app.app_context():
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
        os.makedirs(data_dir, exist_ok=True)

        db.create_all()

        from app.migrations import run_migrations
        run_migrations(db)

        # Create default admin user if none exists
        from app.models import User
        if not User.query.filter_by(username='admin').first():
            admin = User(
                username='admin',
                email='admin@attenddance.local',
                first_name='Admin',
                last_name='User',
                is_admin=True,
            )
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            logger.info("Default admin user created (username: admin, password: admin123)")

        # Both run on every boot (Fly wakes/sleeps several times a day). Never let
        # a single bad row take the whole app down at startup — log and continue.
        try:
            _process_recurring_charges()
        except Exception:
            db.session.rollback()
            logger.exception("Recurring-charge processing failed at startup")
        try:
            _process_auto_reminders()
        except Exception:
            logger.exception("Auto-reminder processing failed at startup")

    @app.before_request
    def _enforce_active_user():
        """Immediately revoke access for a deactivated account. Login already
        blocks inactive users, but an existing session would otherwise stay
        valid until it expires (~8h) — so a just-deactivated teacher/parent
        keeps access. Log them out on their next request instead."""
        from flask import request
        from flask_login import current_user, logout_user
        if request.endpoint == 'static':
            return None
        if current_user.is_authenticated and not current_user.is_active:
            logout_user()
        return None

    @app.before_request
    def _csrf_origin_guard():
        """CSRF defense-in-depth: reject any state-changing request whose Origin
        (or, failing that, Referer) is a different host. Browsers always send
        Origin on cross-site POST/PUT/DELETE, so this blocks the classic CSRF
        without a token on any of the 157 fetch() calls. Pairs with
        SESSION_COOKIE_SAMESITE='Lax'. Server-to-server endpoints authenticate
        by HMAC/token (no browser Origin) and are exempt."""
        from flask import request
        from urllib.parse import urlparse

        if request.method not in ('POST', 'PUT', 'DELETE', 'PATCH'):
            return None
        if request.endpoint in ('api.square_webhook', 'api.cron_run'):
            return None
        source = request.headers.get('Origin') or request.headers.get('Referer')
        if source and urlparse(source).netloc != request.host:
            from flask import jsonify
            logger.warning("Blocked cross-origin %s to %s from %s",
                           request.method, request.path, source)
            return jsonify({'error': 'Cross-origin request blocked'}), 403
        return None

    @app.errorhandler(404)
    def not_found_error(error):
        from flask import render_template
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_error(error):
        from flask import render_template
        db.session.rollback()
        return render_template('errors/500.html'), 500

    @app.context_processor
    def inject_config():
        return {
            'APP_NAME': app.config['APP_NAME'],
            'APP_VERSION': app.config['APP_VERSION'],
        }

    @app.context_processor
    def inject_pending_count():
        """Expose counts for staff nav badges (pending payments, registrations)."""
        from flask_login import current_user
        if not current_user.is_authenticated or not getattr(current_user, 'is_staff', False):
            return {'pending_payment_count': 0, 'registration_count': 0}
        try:
            from app.models import PendingPayment, Registration
            return {
                'pending_payment_count': PendingPayment.query.filter_by(status='pending').count(),
                'registration_count': Registration.query.filter_by(status='pending').count(),
            }
        except Exception:
            return {'pending_payment_count': 0, 'registration_count': 0}

    return app
