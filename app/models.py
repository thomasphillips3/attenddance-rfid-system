"""
Database models for AttenDANCE system
"""

from datetime import datetime, date
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
    role = db.Column(db.String(20), default='teacher', nullable=False)  # admin, teacher, parent
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    invite_code = db.Column(db.String(20), unique=True)
    
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
    
    @property
    def is_parent(self):
        return self.role == 'parent'

    @property
    def is_staff(self):
        return self.role in ('admin', 'teacher')

    def get_children(self):
        """Get students linked to this parent user."""
        if not self.is_parent:
            return []
        return (
            Student.query
            .join(ParentStudent, ParentStudent.student_id == Student.id)
            .filter(ParentStudent.parent_id == self.id)
            .all()
        )

    def __repr__(self):
        return f'<User {self.username}>'

class ParentStudent(db.Model):
    """Links parent users to their children (students)"""
    __tablename__ = 'parent_students'

    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('parent_id', 'student_id', name='unique_parent_student'),
    )

    parent = db.relationship('User', backref='parent_links')
    student = db.relationship('Student', backref='parent_links')

class Family(db.Model):
    """Family account — groups siblings, billing is per-family"""
    __tablename__ = 'families'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    primary_email = db.Column(db.String(120))
    primary_phone = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    students = db.relationship('Student', backref='family', lazy='dynamic')
    def __repr__(self):
        return f'<Family {self.name}>'


class Location(db.Model):
    """Studio location where classes are held"""
    __tablename__ = 'locations'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(200))
    city = db.Column(db.String(100))
    state = db.Column(db.String(2))
    zip_code = db.Column(db.String(10))
    phone = db.Column(db.String(20))
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    classes = db.relationship('DanceClass', backref='location', lazy='dynamic')

    @property
    def full_address(self):
        parts = [self.address, self.city, self.state, self.zip_code]
        return ', '.join(p for p in parts if p)

    def __repr__(self):
        return f'<Location {self.name}>'


class Student(db.Model):
    """Student model"""
    __tablename__ = 'students'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'))

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
    
    # School information
    school = db.Column(db.String(150))
    grade = db.Column(db.String(30))

    # Health / special needs
    allergies = db.Column(db.Text)
    special_needs = db.Column(db.Text)

    # Measurements (for costumes — matches Jackrabbit Sizes tab)
    height = db.Column(db.String(20))
    weight = db.Column(db.String(20))
    shoe_size = db.Column(db.String(20))
    shirt_size = db.Column(db.String(20))
    pants_size = db.Column(db.String(20))
    leotard_size = db.Column(db.String(20))
    dress_size = db.Column(db.String(20))
    waist = db.Column(db.String(20))
    girth = db.Column(db.String(20))
    inseam = db.Column(db.String(20))
    neck = db.Column(db.String(20))
    tight_size = db.Column(db.String(20))
    bust = db.Column(db.String(20))
    hips = db.Column(db.String(20))
    sleeve = db.Column(db.String(20))
    chest = db.Column(db.String(20))
    size_notes = db.Column(db.Text)

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
    transactions = db.relationship('Transaction', backref='student', lazy='dynamic')
    
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
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'))

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
    monthly_fee = db.Column(db.Numeric(10, 2))
    
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

class Transaction(db.Model):
    """Payment / transaction record"""
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)

    type = db.Column(db.String(10), nullable=False, default='payment')  # charge or payment
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    category = db.Column(db.String(50), nullable=False)  # tuition, costumes, shoes, other
    payment_method = db.Column(db.String(50))  # cash, zelle, venmo, cashapp, card, tap (null for charges)
    description = db.Column(db.Text)
    transaction_date = db.Column(db.Date, default=date.today, nullable=False)
    recurring_charge_id = db.Column(db.Integer, db.ForeignKey('recurring_charges.id'))

    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    creator = db.relationship('User', backref='created_transactions')

    recurring_charge = db.relationship('RecurringCharge', backref='transactions')

    def __repr__(self):
        return f'<Transaction ${self.amount} {self.category} for student {self.student_id}>'

class RecurringCharge(db.Model):
    """Automatic monthly charge rule"""
    __tablename__ = 'recurring_charges'

    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    category = db.Column(db.String(50), nullable=False, default='tuition')
    description = db.Column(db.Text)
    day_of_month = db.Column(db.Integer, nullable=False, default=1)  # 1-28
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    dance_class = db.relationship('DanceClass', backref='recurring_charges')
    creator = db.relationship('User', backref='created_recurring_charges')

    def __repr__(self):
        return f'<RecurringCharge ${self.amount} {self.category} for class {self.class_id}>'

class Rule(db.Model):
    """Studio rule that parents must acknowledge"""
    __tablename__ = 'rules'

    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    display_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    acknowledgments = db.relationship('RuleAcknowledgment', backref='rule', lazy='dynamic')

    def __repr__(self):
        return f'<Rule #{self.display_order}>'

class RuleAcknowledgment(db.Model):
    """Record of a parent initialing a specific rule for a student"""
    __tablename__ = 'rule_acknowledgments'

    id = db.Column(db.Integer, primary_key=True)
    rule_id = db.Column(db.Integer, db.ForeignKey('rules.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    initials = db.Column(db.String(10), nullable=False)
    acknowledged_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('rule_id', 'student_id', 'parent_id', name='unique_rule_ack'),
    )

    student = db.relationship('Student', backref='rule_acknowledgments')
    parent = db.relationship('User', backref='rule_acknowledgments')

    def __repr__(self):
        return f'<RuleAck rule={self.rule_id} student={self.student_id}>'

class Message(db.Model):
    """Email blast record"""
    __tablename__ = 'messages'

    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    recipient_type = db.Column(db.String(20), nullable=False)  # all, class, individual
    recipient_filter = db.Column(db.String(100))  # class_id or student_id
    recipient_count = db.Column(db.Integer, default=0)
    recipient_emails = db.Column(db.Text)  # comma-separated
    sent = db.Column(db.Boolean, default=False, nullable=False)
    sent_at = db.Column(db.DateTime)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    creator = db.relationship('User', backref='sent_messages')

    def __repr__(self):
        return f'<Message "{self.subject}" to {self.recipient_count}>' 