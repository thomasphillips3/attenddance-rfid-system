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
                                 ('allergies', 'TEXT'), ('special_needs', 'TEXT')]:
                if col not in student_cols:
                    conn.execute(sqlalchemy.text(f'ALTER TABLE students ADD COLUMN {col} {coltype}'))
            if 'transactions' in inspector.get_table_names():
                txn_cols = [c['name'] for c in inspector.get_columns('transactions')]
                if 'type' not in txn_cols:
                    conn.execute(sqlalchemy.text("ALTER TABLE transactions ADD COLUMN type VARCHAR(10) DEFAULT 'payment'"))
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