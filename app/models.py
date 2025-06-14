"""
Database models for AttenDANCE system
"""

from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db

class User(UserMixin, db.Model):
    """Teacher/Admin user model"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(200), nullable=False)
    
    # Profile information
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(20))
    
    # Permissions
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login = db.Column(db.DateTime)
    
    def set_password(self, password):
        """Set user password hash"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Check user password"""
        return check_password_hash(self.password_hash, password)
    
    @property
    def full_name(self):
        """Get user's full name"""
        return f"{self.first_name} {self.last_name}"
    
    def __repr__(self):
        return f'<User {self.username}>'

class Student(db.Model):
    """Student model"""
    __tablename__ = 'students'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Basic information
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), unique=True, index=True)
    phone = db.Column(db.String(20))
    date_of_birth = db.Column(db.Date)
    
    # Contact information
    emergency_contact_name = db.Column(db.String(100))
    emergency_contact_phone = db.Column(db.String(20))
    parent_email = db.Column(db.String(120))
    
    # RFID information
    rfid_uid = db.Column(db.String(50), unique=True, index=True)
    rfid_assigned_at = db.Column(db.DateTime)
    rfid_assigned_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    # Status
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    enrollment_date = db.Column(db.Date, default=date.today, nullable=False)
    
    # Notes
    notes = db.Column(db.Text)
    medical_notes = db.Column(db.Text)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    assigned_by_user = db.relationship('User', backref='assigned_students')
    attendances = db.relationship('Attendance', backref='student', lazy='dynamic')
    class_enrollments = db.relationship('ClassEnrollment', backref='student', lazy='dynamic')
    
    @property
    def full_name(self):
        """Get student's full name"""
        return f"{self.first_name} {self.last_name}"
    
    @property
    def age(self):
        """Calculate student's age"""
        if self.date_of_birth:
            today = date.today()
            return today.year - self.date_of_birth.year - (
                (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
            )
        return None
    
    def has_rfid(self):
        """Check if student has RFID assigned"""
        return self.rfid_uid is not None
    
    def get_recent_attendance(self, days=30):
        """Get recent attendance records"""
        from datetime import timedelta
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        return self.attendances.filter(Attendance.check_in_time >= cutoff_date).all()
    
    def __repr__(self):
        return f'<Student {self.full_name}>'

class DanceClass(db.Model):
    """Dance class model"""
    __tablename__ = 'classes'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    
    # Schedule
    day_of_week = db.Column(db.Integer, nullable=False)  # 0=Monday, 6=Sunday
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    
    # Instructor
    instructor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Class details
    max_students = db.Column(db.Integer, default=20)
    level = db.Column(db.String(50))  # Beginner, Intermediate, Advanced
    age_group = db.Column(db.String(50))  # Kids, Teens, Adults
    
    # Status
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    instructor = db.relationship('User', backref='taught_classes')
    enrollments = db.relationship('ClassEnrollment', backref='dance_class', lazy='dynamic')
    attendances = db.relationship('Attendance', backref='dance_class', lazy='dynamic')
    
    @property
    def enrolled_students_count(self):
        """Get count of enrolled students"""
        return self.enrollments.filter_by(is_active=True).count()
    
    @property
    def day_name(self):
        """Get day name"""
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        return days[self.day_of_week]
    
    def get_enrolled_students(self):
        """Get list of enrolled students"""
        return [enrollment.student for enrollment in 
                self.enrollments.filter_by(is_active=True).all()]
    
    def get_todays_attendance(self):
        """Get today's attendance for this class"""
        today = date.today()
        return self.attendances.filter(
            db.func.date(Attendance.check_in_time) == today
        ).all()
    
    def __repr__(self):
        return f'<DanceClass {self.name}>'

class ClassEnrollment(db.Model):
    """Student enrollment in classes"""
    __tablename__ = 'class_enrollments'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    
    # Enrollment details
    enrolled_date = db.Column(db.Date, default=date.today, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    
    # Payment/billing (for future use)
    monthly_fee = db.Column(db.Decimal(10, 2))
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Unique constraint
    __table_args__ = (
        db.UniqueConstraint('student_id', 'class_id', name='unique_student_class'),
    )
    
    def __repr__(self):
        return f'<Enrollment {self.student.full_name} in {self.dance_class.name}>'

class Attendance(db.Model):
    """Attendance record model"""
    __tablename__ = 'attendance'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    
    # Attendance details
    check_in_time = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    check_out_time = db.Column(db.DateTime)
    
    # How they checked in
    check_in_method = db.Column(db.String(20), default='rfid')  # rfid, manual, mobile
    
    # Optional notes
    notes = db.Column(db.Text)
    
    # Status
    is_present = db.Column(db.Boolean, default=True, nullable=False)
    
    # Unique constraint to prevent duplicate check-ins on same day
    __table_args__ = (
        db.Index('idx_attendance_date_student', 'student_id', 
                db.func.date('check_in_time'), 'class_id'),
    )
    
    @property
    def attendance_date(self):
        """Get attendance date"""
        return self.check_in_time.date()
    
    @property
    def duration(self):
        """Get attendance duration if checked out"""
        if self.check_out_time:
            return self.check_out_time - self.check_in_time
        return None
    
    def __repr__(self):
        return f'<Attendance {self.student.full_name} on {self.attendance_date}>'

class RFIDLog(db.Model):
    """RFID scan log for debugging and security"""
    __tablename__ = 'rfid_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    rfid_uid = db.Column(db.String(50), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'))
    
    # Scan details
    scan_time = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    action_taken = db.Column(db.String(50))  # checkin, unknown_card, error
    
    # Results
    success = db.Column(db.Boolean, default=False, nullable=False)
    error_message = db.Column(db.String(200))
    
    # Relationships
    student = db.relationship('Student', backref='rfid_logs')
    
    def __repr__(self):
        return f'<RFIDLog {self.rfid_uid} at {self.scan_time}>' 