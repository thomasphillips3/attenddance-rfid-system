"""Seed a demo parent account for testing."""
from app import create_app, db
from app.models import Student, User, ParentStudent

app = create_app()
with app.app_context():
    student = Student.query.filter(Student.parent_email != None).first()
    if not student:
        student = Student.query.first()
    print(f'Linking parent to: {student.full_name} (id={student.id})')

    existing = User.query.filter_by(username='parent-demo').first()
    if existing:
        ParentStudent.query.filter_by(parent_id=existing.id).delete()
        db.session.delete(existing)
        db.session.commit()

    parent = User(
        username='parent-demo',
        email='parent@demo.local',
        first_name='Demo',
        last_name='Parent',
        role='parent',
        is_active=True,
    )
    parent.set_password('parent123')
    db.session.add(parent)
    db.session.flush()

    link = ParentStudent(parent_id=parent.id, student_id=student.id)
    db.session.add(link)
    db.session.commit()
    print(f'Parent login: parent-demo / parent123')
    print(f'Linked to: {student.full_name}')
