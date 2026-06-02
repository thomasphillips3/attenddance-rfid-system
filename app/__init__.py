"""
Flask application factory for AttenDANCE system
"""

import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from config.config import config

# Initialize extensions
db = SQLAlchemy()
login_manager = LoginManager()

def _process_recurring_charges():
    """Create charge transactions for any recurring charges due this month."""
    from datetime import date
    from app.models import RecurringCharge, Transaction, ClassEnrollment
    today = date.today()
    actives = RecurringCharge.query.filter_by(is_active=True).all()
    for rc in actives:
        if today.day < rc.day_of_month:
            continue
        # Check if already processed this month
        month_start = today.replace(day=1)
        already = Transaction.query.filter_by(
            recurring_charge_id=rc.id,
        ).filter(Transaction.transaction_date >= month_start).first()
        if already:
            continue
        # Create charges for all enrolled students
        enrollments = ClassEnrollment.query.filter_by(class_id=rc.class_id, is_active=True).all()
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
        db.session.commit()
        print(f"✅ Recurring charge #{rc.id}: charged {len(enrollments)} students ${rc.amount} for {rc.dance_class.name}")

def create_app(config_name=None):
    """Application factory function"""
    
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')
    
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    
    # Initialize extensions with app
    db.init_app(app)
    login_manager.init_app(app)
    
    # Configure login manager
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'
    
    @login_manager.user_loader
    def load_user(user_id):
        from app.models import User
        return User.query.get(int(user_id))
    
    # Register blueprints
    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')
    
    from app.api import bp as api_bp
    app.register_blueprint(api_bp, url_prefix='/api')
    
    from app.main import bp as main_bp
    app.register_blueprint(main_bp)
    
    # Create database tables
    with app.app_context():
        # Create data directory if it doesn't exist
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
        os.makedirs(data_dir, exist_ok=True)
        
        # Create all database tables
        db.create_all()

        # Add new columns to existing tables (SQLite ALTER TABLE)
        import sqlalchemy
        with db.engine.connect() as conn:
            inspector = sqlalchemy.inspect(db.engine)
            student_cols = [c['name'] for c in inspector.get_columns('students')]
            for col, coltype in [('school', 'VARCHAR(150)'), ('grade', 'VARCHAR(30)'),
                                 ('allergies', 'TEXT'), ('special_needs', 'TEXT'),
                                 ('family_id', 'INTEGER'), ('height', 'VARCHAR(20)'),
                                 ('weight', 'VARCHAR(20)'), ('shoe_size', 'VARCHAR(20)'),
                                 ('shirt_size', 'VARCHAR(20)'), ('pants_size', 'VARCHAR(20)'),
                                 ('leotard_size', 'VARCHAR(20)')]:
                if col not in student_cols:
                    conn.execute(sqlalchemy.text(f'ALTER TABLE students ADD COLUMN {col} {coltype}'))
            user_cols = [c['name'] for c in inspector.get_columns('users')]
            if 'role' not in user_cols:
                conn.execute(sqlalchemy.text("ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'teacher'"))
            if 'invite_code' not in user_cols:
                conn.execute(sqlalchemy.text("ALTER TABLE users ADD COLUMN invite_code VARCHAR(20)"))
            if 'transactions' in inspector.get_table_names():
                txn_cols = [c['name'] for c in inspector.get_columns('transactions')]
                if 'type' not in txn_cols:
                    conn.execute(sqlalchemy.text("ALTER TABLE transactions ADD COLUMN type VARCHAR(10) DEFAULT 'payment'"))
                if 'recurring_charge_id' not in txn_cols:
                    conn.execute(sqlalchemy.text("ALTER TABLE transactions ADD COLUMN recurring_charge_id INTEGER"))
            conn.commit()
        
        # Create default admin user if none exists
        from app.models import User
        if not User.query.filter_by(username='admin').first():
            admin = User(
                username='admin',
                email='admin@attenddance.local',
                first_name='Admin',
                last_name='User',
                is_admin=True
            )
            admin.set_password('admin123')  # Change this in production!
            db.session.add(admin)
            db.session.commit()
            print("✅ Default admin user created (username: admin, password: admin123)")

        # Process any due recurring charges
        _process_recurring_charges()

    # Error handlers
    @app.errorhandler(404)
    def not_found_error(error):
        from flask import render_template
        return render_template('errors/404.html'), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        from flask import render_template
        db.session.rollback()
        return render_template('errors/500.html'), 500
    
    # Template context processors
    @app.context_processor
    def inject_config():
        return {
            'APP_NAME': app.config['APP_NAME'],
            'APP_VERSION': app.config['APP_VERSION']
        }
    
    return app 