"""Database schema migrations for AttenDANCE.
Adds columns to existing tables on startup (SQLite ALTER TABLE).
"""

import sqlalchemy


STUDENT_COLUMNS = [
    ('school', 'VARCHAR(150)'), ('grade', 'VARCHAR(30)'),
    ('allergies', 'TEXT'), ('special_needs', 'TEXT'),
    ('family_id', 'INTEGER'), ('height', 'VARCHAR(20)'),
    ('weight', 'VARCHAR(20)'), ('shoe_size', 'VARCHAR(20)'),
    ('shirt_size', 'VARCHAR(20)'), ('pants_size', 'VARCHAR(20)'),
    ('leotard_size', 'VARCHAR(20)'), ('dress_size', 'VARCHAR(20)'),
    ('waist', 'VARCHAR(20)'), ('girth', 'VARCHAR(20)'),
    ('inseam', 'VARCHAR(20)'), ('neck', 'VARCHAR(20)'),
    ('tight_size', 'VARCHAR(20)'), ('bust', 'VARCHAR(20)'),
    ('hips', 'VARCHAR(20)'), ('sleeve', 'VARCHAR(20)'),
    ('chest', 'VARCHAR(20)'), ('size_notes', 'TEXT'),
    ('parent_phone', 'VARCHAR(20)'),
]

USER_COLUMNS = [
    ('role', "VARCHAR(20) DEFAULT 'teacher'"),
    ('invite_code', 'VARCHAR(20)'),
]

TRANSACTION_COLUMNS = [
    ('type', "VARCHAR(10) DEFAULT 'payment'"),
    ('recurring_charge_id', 'INTEGER'),
]

CLASS_COLUMNS = [
    ('location_id', 'INTEGER'),
]

PERFORMANCE_COLUMNS = [
    ('recital_id', 'INTEGER'),
]


def _add_missing_columns(conn, inspector, table, columns):
    existing = [c['name'] for c in inspector.get_columns(table)]
    for col, coltype in columns:
        if col not in existing:
            conn.execute(sqlalchemy.text(f'ALTER TABLE {table} ADD COLUMN {col} {coltype}'))


def run_migrations(db):
    with db.engine.connect() as conn:
        inspector = sqlalchemy.inspect(db.engine)
        _add_missing_columns(conn, inspector, 'students', STUDENT_COLUMNS)
        _add_missing_columns(conn, inspector, 'users', USER_COLUMNS)
        if 'transactions' in inspector.get_table_names():
            _add_missing_columns(conn, inspector, 'transactions', TRANSACTION_COLUMNS)
        if 'classes' in inspector.get_table_names():
            _add_missing_columns(conn, inspector, 'classes', CLASS_COLUMNS)
        if 'performances' in inspector.get_table_names():
            _add_missing_columns(conn, inspector, 'performances', PERFORMANCE_COLUMNS)
        conn.commit()
