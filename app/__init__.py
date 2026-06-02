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
    from datetime import date

    from app.models import ClassEnrollment, RecurringCharge, Transaction

    today = date.today()
    month_start = today.replace(day=1)
    actives = RecurringCharge.query.filter_by(is_active=True).all()

    for rc in actives:
        if today.day < rc.day_of_month:
            continue
        already = Transaction.query.filter_by(
            recurring_charge_id=rc.id,
        ).filter(Transaction.transaction_date >= month_start).first()
        if already:
            continue
        enrollments = ClassEnrollment.query.filter_by(
            class_id=rc.class_id, is_active=True
        ).all()
        charge_date = today.replace(day=rc.day_of_month) if today.day >= rc.day_of_month else today
        for e in enrollments:
            t = Transaction(
                student_id=e.student_id,
                type='charge',
                amount=rc.amount,
                category=rc.category,
                payment_method='n/a',
                description=rc.description or f'{rc.dance_class.name} - {rc.category}',
                transaction_date=charge_date,
                recurring_charge_id=rc.id,
                created_by=rc.created_by,
            )
            db.session.add(t)
        logger.info(
            "Recurring charge #%d: charged %d students $%s for %s",
            rc.id, len(enrollments), rc.amount, rc.dance_class.name,
        )

    db.session.commit()


def create_app(config_name=None):
    """Application factory function."""
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

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

        _process_recurring_charges()

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

    return app
