"""
REST API routes for AttenDANCE system
"""

from datetime import datetime, date, timedelta
from flask import request, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import and_, or_, desc, func

from app.api import bp
from app.models import User, Student, DanceClass, ClassEnrollment, Attendance, RFIDLog, Transaction, RecurringCharge, ParentStudent, Rule, RuleAcknowledgment, Message, Family
import secrets
from app import square_service
from app import db
try:
    from rfid.service import get_rfid_service
except ImportError:
    get_rfid_service = None

# Helper functions
def get_paginated_response(query, page, per_page, endpoint, **kwargs):
    """Helper to generate paginated JSON responses"""
    pagination = query.paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return {
        'items': [item.to_dict() if hasattr(item, 'to_dict') else item for item in pagination.items],
        'pagination': {
            'page': page,
            'pages': pagination.pages,
            'per_page': per_page,
            'total': pagination.total,
            'has_next': pagination.has_next,
            'has_prev': pagination.has_prev,
            'next_num': pagination.next_num,
            'prev_num': pagination.prev_num
        }
    }

def student_to_dict(student):
    """Convert student object to dictionary"""
    return {
        'id': student.id,
        'first_name': student.first_name,
        'last_name': student.last_name,
        'full_name': student.full_name,
        'email': student.email,
        'phone': student.phone,
        'date_of_birth': student.date_of_birth.isoformat() if student.date_of_birth else None,
        'age': student.age,
        'emergency_contact_name': student.emergency_contact_name,
        'emergency_contact_phone': student.emergency_contact_phone,
        'parent_email': student.parent_email,
        'school': student.school,
        'grade': student.grade,
        'allergies': student.allergies,
        'special_needs': student.special_needs,
        'height': student.height,
        'weight': student.weight,
        'shoe_size': student.shoe_size,
        'shirt_size': student.shirt_size,
        'pants_size': student.pants_size,
        'leotard_size': student.leotard_size,
        'family_id': student.family_id,
        'family_name': student.family.name if student.family else None,
        'rfid_uid': student.rfid_uid,
        'has_rfid': student.has_rfid(),
        'rfid_assigned_at': student.rfid_assigned_at.isoformat() if student.rfid_assigned_at else None,
        'is_active': student.is_active,
        'enrollment_date': student.enrollment_date.isoformat(),
        'notes': student.notes,
        'medical_notes': student.medical_notes,
        'created_at': student.created_at.isoformat(),
        'updated_at': student.updated_at.isoformat()
    }

def class_to_dict(dance_class):
    """Convert class object to dictionary"""
    return {
        'id': dance_class.id,
        'name': dance_class.name,
        'description': dance_class.description,
        'day_of_week': dance_class.day_of_week,
        'day_name': dance_class.day_name,
        'start_time': dance_class.start_time.strftime('%H:%M'),
        'end_time': dance_class.end_time.strftime('%H:%M'),
        'instructor_id': dance_class.instructor_id,
        'instructor_name': dance_class.instructor.full_name,
        'max_students': dance_class.max_students,
        'enrolled_count': dance_class.enrolled_students_count,
        'level': dance_class.level,
        'age_group': dance_class.age_group,
        'is_active': dance_class.is_active,
        'created_at': dance_class.created_at.isoformat(),
        'updated_at': dance_class.updated_at.isoformat()
    }

def attendance_to_dict(attendance):
    """Convert attendance object to dictionary"""
    return {
        'id': attendance.id,
        'student_id': attendance.student_id,
        'student_name': attendance.student.full_name,
        'class_id': attendance.class_id,
        'class_name': attendance.dance_class.name,
        'check_in_time': attendance.check_in_time.isoformat(),
        'check_out_time': attendance.check_out_time.isoformat() if attendance.check_out_time else None,
        'check_in_method': attendance.check_in_method,
        'notes': attendance.notes,
        'is_present': attendance.is_present,
        'attendance_date': attendance.attendance_date.isoformat(),
        'duration': str(attendance.duration) if attendance.duration else None
    }

# Authentication endpoints
@bp.route('/auth/login', methods=['POST'])
def api_login():
    """API login endpoint"""
    # This is handled by the auth blueprint, but we include it here for API documentation
    return jsonify({'message': 'Use /auth/login endpoint'}), 400

@bp.route('/auth/logout', methods=['POST'])
@login_required
def api_logout():
    """API logout endpoint"""
    # This is handled by the auth blueprint
    return jsonify({'message': 'Use /auth/logout endpoint'}), 400

@bp.route('/auth/me')
@login_required
def api_current_user():
    """Get current user info"""
    return jsonify({
        'id': current_user.id,
        'username': current_user.username,
        'email': current_user.email,
        'full_name': current_user.full_name,
        'first_name': current_user.first_name,
        'last_name': current_user.last_name,
        'is_admin': current_user.is_admin,
        'last_login': current_user.last_login.isoformat() if current_user.last_login else None
    })

# Student endpoints
@bp.route('/students', methods=['GET'])
@login_required
def get_students():
    """Get list of students with pagination and filtering"""
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    search = request.args.get('search', '').strip()
    active_only = request.args.get('active', 'true').lower() == 'true'
    
    query = Student.query
    
    if active_only:
        query = query.filter_by(is_active=True)
    
    if search:
        query = query.filter(
            or_(
                Student.first_name.contains(search),
                Student.last_name.contains(search),
                Student.email.contains(search)
            )
        )
    
    query = query.order_by(Student.last_name, Student.first_name)
    
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        'students': [student_to_dict(student) for student in pagination.items],
        'pagination': {
            'page': page,
            'pages': pagination.pages,
            'per_page': per_page,
            'total': pagination.total,
            'has_next': pagination.has_next,
            'has_prev': pagination.has_prev
        }
    })

@bp.route('/students/<int:student_id>', methods=['GET'])
@login_required
def get_student(student_id):
    """Get single student by ID"""
    student = Student.query.get_or_404(student_id)
    return jsonify(student_to_dict(student))

@bp.route('/students', methods=['POST'])
@login_required
def create_student():
    """Create new student"""
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    required_fields = ['first_name', 'last_name']
    for field in required_fields:
        if not data.get(field):
            return jsonify({'error': f'{field} is required'}), 400
    
    # Check for duplicate email
    if data.get('email'):
        existing = Student.query.filter_by(email=data['email']).first()
        if existing:
            return jsonify({'error': 'Email already exists'}), 400
    
    try:
        student = Student(
            first_name=data['first_name'].strip(), 
            last_name=data['last_name'].strip(),
            email=data.get('email', '').strip() or None,
            phone=data.get('phone', '').strip() or None,
            date_of_birth=datetime.strptime(data['date_of_birth'], '%Y-%m-%d').date() if data.get('date_of_birth') else None,
            emergency_contact_name=data.get('emergency_contact_name', '').strip() or None,
            emergency_contact_phone=data.get('emergency_contact_phone', '').strip() or None,
            parent_email=data.get('parent_email', '').strip() or None,
            school=data.get('school', '').strip() or None,
            grade=data.get('grade', '').strip() or None,
            allergies=data.get('allergies', '').strip() or None,
            special_needs=data.get('special_needs', '').strip() or None,
            height=data.get('height', '').strip() or None,
            weight=data.get('weight', '').strip() or None,
            shoe_size=data.get('shoe_size', '').strip() or None,
            shirt_size=data.get('shirt_size', '').strip() or None,
            pants_size=data.get('pants_size', '').strip() or None,
            leotard_size=data.get('leotard_size', '').strip() or None,
            family_id=int(data['family_id']) if data.get('family_id') else None,
            notes=data.get('notes', '').strip() or None,
            medical_notes=data.get('medical_notes', '').strip() or None
        )
        
        db.session.add(student)
        db.session.commit()
        
        return jsonify(student_to_dict(student)), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@bp.route('/students/<int:student_id>', methods=['PUT'])
@login_required
def update_student(student_id):
    """Update student"""
    student = Student.query.get_or_404(student_id)
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    try:
        # Update fields if provided
        if 'first_name' in data:
            student.first_name = data['first_name'].strip()
        if 'last_name' in data:
            student.last_name = data['last_name'].strip()
        if 'email' in data:
            email = data['email'].strip() or None
            if email and email != student.email:
                existing = Student.query.filter_by(email=email).first()
                if existing:
                    return jsonify({'error': 'Email already exists'}), 400
            student.email = email
        if 'phone' in data:
            student.phone = data['phone'].strip() or None
        if 'date_of_birth' in data:
            student.date_of_birth = datetime.strptime(data['date_of_birth'], '%Y-%m-%d').date() if data['date_of_birth'] else None
        if 'emergency_contact_name' in data:
            student.emergency_contact_name = data['emergency_contact_name'].strip() or None
        if 'emergency_contact_phone' in data:
            student.emergency_contact_phone = data['emergency_contact_phone'].strip() or None
        if 'parent_email' in data:
            student.parent_email = data['parent_email'].strip() or None
        if 'school' in data:
            student.school = data['school'].strip() or None
        if 'grade' in data:
            student.grade = data['grade'].strip() or None
        if 'allergies' in data:
            student.allergies = data['allergies'].strip() or None
        if 'special_needs' in data:
            student.special_needs = data['special_needs'].strip() or None
        for mfield in ['height', 'weight', 'shoe_size', 'shirt_size', 'pants_size', 'leotard_size']:
            if mfield in data:
                setattr(student, mfield, data[mfield].strip() or None)
        if 'family_id' in data:
            student.family_id = int(data['family_id']) if data['family_id'] else None
        if 'notes' in data:
            student.notes = data['notes'].strip() or None
        if 'medical_notes' in data:
            student.medical_notes = data['medical_notes'].strip() or None
        if 'is_active' in data:
            student.is_active = bool(data['is_active'])
        
        student.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify(student_to_dict(student))
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@bp.route('/students/<int:student_id>', methods=['DELETE'])
@login_required
def delete_student(student_id):
    """Delete student (soft delete)"""
    student = Student.query.get_or_404(student_id)
    
    # Soft delete - just deactivate
    student.is_active = False
    student.updated_at = datetime.utcnow()
    db.session.commit()
    
    return jsonify({'message': 'Student deactivated successfully'})

@bp.route('/students/<int:student_id>/assign-rfid', methods=['POST'])
@login_required
def assign_rfid(student_id):
    """Assign RFID card to student"""
    student = Student.query.get_or_404(student_id)
    data = request.get_json()
    
    rfid_uid = data.get('rfid_uid', '').strip() if data else ''
    
    if not rfid_uid:
        return jsonify({'error': 'RFID UID is required'}), 400
    
    # Check if RFID is already assigned
    existing = Student.query.filter_by(rfid_uid=rfid_uid).first()
    if existing and existing.id != student_id:
        return jsonify({'error': 'RFID card is already assigned to another student'}), 400
    
    student.rfid_uid = rfid_uid
    student.rfid_assigned_at = datetime.utcnow()
    student.rfid_assigned_by = current_user.id
    student.updated_at = datetime.utcnow()
    
    db.session.commit()
    
    return jsonify({'message': 'RFID card assigned successfully', 'student': student_to_dict(student)})

@bp.route('/students/<int:student_id>/remove-rfid', methods=['POST'])
@login_required
def remove_rfid(student_id):
    """Remove RFID card from student"""
    student = Student.query.get_or_404(student_id)
    
    student.rfid_uid = None
    student.rfid_assigned_at = None
    student.rfid_assigned_by = None
    student.updated_at = datetime.utcnow()
    
    db.session.commit()
    
    return jsonify({'message': 'RFID card removed successfully', 'student': student_to_dict(student)})

# Class endpoints
@bp.route('/classes', methods=['GET'])
@login_required
def get_classes():
    """Get list of classes"""
    active_only = request.args.get('active', 'true').lower() == 'true'
    
    query = DanceClass.query
    if active_only:
        query = query.filter_by(is_active=True)
    
    query = query.order_by(DanceClass.day_of_week, DanceClass.start_time)
    classes = query.all()
    
    return jsonify({
        'classes': [class_to_dict(cls) for cls in classes]
    })

@bp.route('/classes/<int:class_id>', methods=['GET'])
@login_required
def get_class(class_id):
    """Get single class by ID"""
    dance_class = DanceClass.query.get_or_404(class_id)
    return jsonify(class_to_dict(dance_class))

@bp.route('/classes', methods=['POST'])
@login_required
def create_class():
    """Create new class"""
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    required_fields = ['name', 'day_of_week', 'start_time', 'end_time']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'{field} is required'}), 400

    try:
        dance_class = DanceClass(
            name=data['name'].strip(),
            description=data.get('description', '').strip() or None,
            day_of_week=int(data['day_of_week']),
            start_time=datetime.strptime(data['start_time'], '%H:%M').time(),
            end_time=datetime.strptime(data['end_time'], '%H:%M').time(),
            instructor_id=int(data.get('instructor_id', current_user.id)),
            max_students=data.get('max_students', 20),
            level=data.get('level', '').strip() or None,
            age_group=data.get('age_group', '').strip() or None
        )
        
        db.session.add(dance_class)
        db.session.commit()
        
        return jsonify(class_to_dict(dance_class)), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# Enrollment endpoints
@bp.route('/classes/<int:class_id>/enrollments', methods=['GET'])
@login_required
def get_class_enrollments(class_id):
    """Get students enrolled in a class"""
    dance_class = DanceClass.query.get_or_404(class_id)
    enrollments = ClassEnrollment.query.filter_by(
        class_id=class_id, is_active=True
    ).all()
    students = []
    for e in enrollments:
        s = Student.query.get(e.student_id)
        if s:
            students.append({
                'enrollment_id': e.id,
                'student_id': s.id,
                'full_name': s.full_name,
                'email': s.email,
                'has_rfid': s.has_rfid(),
                'enrolled_date': e.enrolled_date.isoformat(),
            })
    return jsonify({'enrollments': students, 'class_name': dance_class.name})

@bp.route('/classes/<int:class_id>/enroll', methods=['POST'])
@login_required
def enroll_student(class_id):
    """Enroll one or more students in a class"""
    dance_class = DanceClass.query.get_or_404(class_id)
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    # Accept single student_id or batch student_ids
    student_ids = data.get('student_ids', [])
    if not student_ids and data.get('student_id'):
        student_ids = [int(data['student_id'])]
    if not student_ids:
        return jsonify({'error': 'student_id or student_ids is required'}), 400

    enrolled = []
    skipped = []
    for sid in student_ids:
        student = Student.query.get(int(sid))
        if not student:
            continue
        existing = ClassEnrollment.query.filter_by(
            student_id=student.id, class_id=class_id
        ).first()
        if existing:
            if existing.is_active:
                skipped.append(student.full_name)
                continue
            existing.is_active = True
            existing.enrolled_date = date.today()
        else:
            db.session.add(ClassEnrollment(student_id=student.id, class_id=class_id))
        enrolled.append(student.full_name)

    db.session.commit()
    msg = f'{len(enrolled)} student(s) enrolled in {dance_class.name}'
    if skipped:
        msg += f' ({len(skipped)} already enrolled)'
    return jsonify({'message': msg, 'enrolled': enrolled, 'skipped': skipped}), 201

@bp.route('/enrollments/<int:enrollment_id>', methods=['DELETE'])
@login_required
def unenroll_student(enrollment_id):
    """Unenroll a student from a class"""
    enrollment = ClassEnrollment.query.get_or_404(enrollment_id)
    enrollment.is_active = False
    db.session.commit()
    return jsonify({'message': 'Student unenrolled successfully'})

@bp.route('/attendance/toggle', methods=['POST'])
@login_required
def toggle_attendance():
    """Toggle attendance for a student in a class on a given date"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    student_id = data.get('student_id')
    class_id = data.get('class_id')
    att_date = data.get('date')  # ISO format YYYY-MM-DD
    if not all([student_id, class_id]):
        return jsonify({'error': 'student_id and class_id required'}), 400

    target_date = datetime.strptime(att_date, '%Y-%m-%d').date() if att_date else date.today()

    existing = Attendance.query.filter(
        Attendance.student_id == student_id,
        Attendance.class_id == class_id,
        func.date(Attendance.check_in_time) == target_date,
    ).first()

    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({'present': False, 'message': 'Attendance removed'})
    else:
        att = Attendance(
            student_id=student_id,
            class_id=class_id,
            check_in_time=datetime.combine(target_date, datetime.now().time()),
            check_in_method='manual',
            is_present=True,
        )
        db.session.add(att)
        db.session.commit()
        return jsonify({'present': True, 'message': 'Marked present'}), 201

# Attendance endpoints
@bp.route('/attendance', methods=['GET'])
@login_required
def get_attendance():
    """Get attendance records with filtering"""
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 100)
    
    # Date filtering
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    class_id = request.args.get('class_id', type=int)
    student_id = request.args.get('student_id', type=int)
    
    query = Attendance.query
    
    if date_from:
        query = query.filter(func.date(Attendance.check_in_time) >= datetime.strptime(date_from, '%Y-%m-%d').date())
    if date_to:
        query = query.filter(func.date(Attendance.check_in_time) <= datetime.strptime(date_to, '%Y-%m-%d').date())
    if class_id:
        query = query.filter_by(class_id=class_id)
    if student_id:
        query = query.filter_by(student_id=student_id)
    
    query = query.order_by(desc(Attendance.check_in_time))
    
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        'attendance': [attendance_to_dict(att) for att in pagination.items],
        'pagination': {
            'page': page,
            'pages': pagination.pages,
            'per_page': per_page,
            'total': pagination.total,
            'has_next': pagination.has_next,
            'has_prev': pagination.has_prev
        }
    })

@bp.route('/attendance/today', methods=['GET'])
@login_required
def get_todays_attendance():
    """Get today's attendance"""
    today = date.today()
    class_id = request.args.get('class_id', type=int)
    
    query = Attendance.query.filter(func.date(Attendance.check_in_time) == today)
    
    if class_id:
        query = query.filter_by(class_id=class_id)
    
    attendance_records = query.order_by(desc(Attendance.check_in_time)).all()
    
    return jsonify({
        'date': today.isoformat(),
        'attendance': [attendance_to_dict(att) for att in attendance_records],
        'count': len(attendance_records)
    })

@bp.route('/attendance/checkin', methods=['POST'])
@login_required
def manual_checkin():
    """Manual check-in for student"""
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    student_id = data.get('student_id')
    class_id = data.get('class_id')
    
    if not student_id or not class_id:
        return jsonify({'error': 'student_id and class_id are required'}), 400
    
    # Verify student and class exist
    student = Student.query.get_or_404(student_id)
    dance_class = DanceClass.query.get_or_404(class_id)
    
    # Check if already checked in today
    today = date.today()
    existing = Attendance.query.filter(
        Attendance.student_id == student_id,
        Attendance.class_id == class_id,
        func.date(Attendance.check_in_time) == today
    ).first()
    
    if existing:
        return jsonify({'error': 'Student already checked in today'}), 400
    
    try:
        attendance = Attendance(
            student_id=student_id,
            class_id=class_id,
            check_in_time=datetime.utcnow(),
            check_in_method='manual',
            notes=data.get('notes', '').strip() or None,
            is_present=True
        )
        
        db.session.add(attendance)
        db.session.commit()
        
        return jsonify({
            'message': f'{student.full_name} checked in successfully',
            'attendance': attendance_to_dict(attendance)
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# RFID endpoints
@bp.route('/rfid/status', methods=['GET'])
@login_required
def rfid_status():
    """Get RFID service status"""
    if not get_rfid_service:
        return jsonify({'service_running': False, 'message': 'RFID not available'}), 200
    service = get_rfid_service()
    stats = service.get_stats()
    
    return jsonify({
        'service_running': stats['running'],
        'total_scans': stats['total_scans'],
        'successful_checkins': stats['successful_checkins'],
        'failed_scans': stats['failed_scans'],
        'last_scan_time': stats['last_scan_time'].isoformat() if stats['last_scan_time'] else None,
        'last_scan_uid': stats['last_scan_uid']
    })

@bp.route('/rfid/simulate', methods=['POST'])
@login_required
def simulate_rfid_scan():
    """Simulate RFID scan for testing"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    data = request.get_json()
    uid = data.get('uid') if data else None
    
    if not uid:
        return jsonify({'error': 'UID is required'}), 400
    
    if not get_rfid_service:
        return jsonify({'error': 'RFID not available'}), 400
    service = get_rfid_service()
    success = service.simulate_scan(uid)
    
    return jsonify({
        'success': success,
        'message': f'Simulated scan for UID: {uid}'
    })

@bp.route('/rfid/logs', methods=['GET'])
@login_required
def get_rfid_logs():
    """Get RFID scan logs"""
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 100)
    
    query = RFIDLog.query.order_by(desc(RFIDLog.scan_time))
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    logs = []
    for log in pagination.items:
        logs.append({
            'id': log.id,
            'rfid_uid': log.rfid_uid,
            'student_id': log.student_id,
            'student_name': log.student.full_name if log.student else None,
            'scan_time': log.scan_time.isoformat(),
            'action_taken': log.action_taken,
            'success': log.success,
            'error_message': log.error_message
        })
    
    return jsonify({
        'logs': logs,
        'pagination': {
            'page': page,
            'pages': pagination.pages,
            'per_page': per_page,
            'total': pagination.total,
            'has_next': pagination.has_next,
            'has_prev': pagination.has_prev
        }
    })

# Dashboard/Stats endpoints
@bp.route('/dashboard/stats', methods=['GET'])
@login_required
def dashboard_stats():
    """Get dashboard statistics"""
    today = date.today()
    
    # Basic counts
    total_students = Student.query.filter_by(is_active=True).count()
    total_classes = DanceClass.query.filter_by(is_active=True).count()
    
    # Today's attendance
    todays_attendance = Attendance.query.filter(
        func.date(Attendance.check_in_time) == today
    ).count()
    
    # This week's attendance
    week_start = today - timedelta(days=today.weekday())
    week_attendance = Attendance.query.filter(
        func.date(Attendance.check_in_time) >= week_start
    ).count()
    
    # Recent RFID activity
    recent_rfid_logs = RFIDLog.query.filter(
        RFIDLog.scan_time >= datetime.utcnow() - timedelta(days=1)
    ).count()
    
    return jsonify({
        'total_students': total_students,
        'total_classes': total_classes,
        'todays_attendance': todays_attendance,
        'week_attendance': week_attendance,
        'recent_rfid_activity': recent_rfid_logs,
        'date': today.isoformat()
    })

# Transaction endpoints
def transaction_to_dict(t):
    return {
        'id': t.id,
        'student_id': t.student_id,
        'student_name': t.student.full_name,
        'type': t.type or 'payment',
        'amount': str(t.amount),
        'category': t.category,
        'payment_method': t.payment_method if t.payment_method != 'n/a' else None,
        'description': t.description,
        'transaction_date': t.transaction_date.isoformat(),
        'created_by': t.creator.full_name if t.creator else None,
        'created_at': t.created_at.isoformat(),
    }

@bp.route('/transactions', methods=['GET'])
@login_required
def get_transactions():
    """Get transactions with optional filtering"""
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 100)
    student_id = request.args.get('student_id', type=int)
    category = request.args.get('category', '').strip()

    query = Transaction.query
    if student_id:
        query = query.filter_by(student_id=student_id)
    if category:
        query = query.filter_by(category=category)
    query = query.order_by(desc(Transaction.transaction_date), desc(Transaction.created_at))

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        'transactions': [transaction_to_dict(t) for t in pagination.items],
        'pagination': {
            'page': page,
            'pages': pagination.pages,
            'per_page': per_page,
            'total': pagination.total,
        }
    })

@bp.route('/transactions', methods=['POST'])
@login_required
def create_transaction():
    """Create a new transaction"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    txn_type = data.get('type', 'payment')
    for field in ['student_id', 'amount', 'category']:
        if not data.get(field):
            return jsonify({'error': f'{field} is required'}), 400
    if txn_type == 'payment' and not data.get('payment_method'):
        return jsonify({'error': 'payment_method is required for payments'}), 400

    student = Student.query.get(data['student_id'])
    if not student:
        return jsonify({'error': 'Student not found'}), 404

    try:
        t = Transaction(
            student_id=student.id,
            type=txn_type,
            amount=data['amount'],
            category=data['category'],
            payment_method=data.get('payment_method') or 'n/a',
            description=data.get('description', '').strip() or None,
            transaction_date=datetime.strptime(data['transaction_date'], '%Y-%m-%d').date() if data.get('transaction_date') else date.today(),
            created_by=current_user.id,
        )
        db.session.add(t)
        db.session.commit()
        return jsonify(transaction_to_dict(t)), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@bp.route('/balances', methods=['GET'])
@login_required
def get_balances():
    """Get balance summary for all active students"""
    students = Student.query.filter_by(is_active=True).order_by(Student.last_name, Student.first_name).all()
    balances = []
    for s in students:
        txns = Transaction.query.filter_by(student_id=s.id).all()
        total_charges = sum(float(t.amount) for t in txns if (t.type or 'payment') == 'charge')
        total_payments = sum(float(t.amount) for t in txns if (t.type or 'payment') == 'payment')
        balance = total_charges - total_payments
        balances.append({
            'student_id': s.id,
            'student_name': s.full_name,
            'total_charges': f'{total_charges:.2f}',
            'total_payments': f'{total_payments:.2f}',
            'balance': f'{balance:.2f}',
        })
    return jsonify({'balances': balances})

@bp.route('/students/<int:student_id>/ledger', methods=['GET'])
@login_required
def get_student_ledger(student_id):
    """Get full ledger for a student with running balance"""
    student = Student.query.get_or_404(student_id)
    txns = Transaction.query.filter_by(student_id=student_id).order_by(
        Transaction.transaction_date, Transaction.created_at
    ).all()
    running = 0.0
    ledger = []
    for t in txns:
        amt = float(t.amount)
        if (t.type or 'payment') == 'charge':
            running += amt
        else:
            running -= amt
        ledger.append({
            **transaction_to_dict(t),
            'running_balance': f'{running:.2f}',
        })
    total_charges = sum(float(t.amount) for t in txns if (t.type or 'payment') == 'charge')
    total_payments = sum(float(t.amount) for t in txns if (t.type or 'payment') == 'payment')

    categories = set(t.category for t in txns)
    by_category = {}
    for cat in sorted(categories):
        cat_charges = sum(float(t.amount) for t in txns if (t.type or 'payment') == 'charge' and t.category == cat)
        cat_payments = sum(float(t.amount) for t in txns if (t.type or 'payment') == 'payment' and t.category == cat)
        by_category[cat] = {
            'charges': f'{cat_charges:.2f}',
            'payments': f'{cat_payments:.2f}',
            'balance': f'{cat_charges - cat_payments:.2f}',
        }

    return jsonify({
        'student_id': student.id,
        'student_name': student.full_name,
        'ledger': ledger,
        'total_charges': f'{total_charges:.2f}',
        'total_payments': f'{total_payments:.2f}',
        'balance': f'{total_charges - total_payments:.2f}',
        'by_category': by_category,
    })

@bp.route('/transactions/bulk-charge', methods=['POST'])
@login_required
def bulk_charge():
    """Charge all enrolled students in a class"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    for field in ['class_id', 'amount', 'category']:
        if not data.get(field):
            return jsonify({'error': f'{field} is required'}), 400

    dance_class = DanceClass.query.get(data['class_id'])
    if not dance_class:
        return jsonify({'error': 'Class not found'}), 404

    enrollments = ClassEnrollment.query.filter_by(class_id=dance_class.id, is_active=True).all()
    if not enrollments:
        return jsonify({'error': 'No students enrolled in this class'}), 400

    charged = []
    for e in enrollments:
        t = Transaction(
            student_id=e.student_id,
            type='charge',
            amount=data['amount'],
            category=data['category'],
            payment_method='n/a',
            description=data.get('description', '').strip() or f'{dance_class.name} - {data["category"]}',
            transaction_date=datetime.strptime(data['transaction_date'], '%Y-%m-%d').date() if data.get('transaction_date') else date.today(),
            created_by=current_user.id,
        )
        db.session.add(t)
        charged.append(e.student_id)
    db.session.commit()
    return jsonify({'message': f'Charged {len(charged)} students', 'count': len(charged)}), 201

# Recurring charge endpoints
def recurring_to_dict(rc):
    return {
        'id': rc.id,
        'class_id': rc.class_id,
        'class_name': rc.dance_class.name,
        'amount': str(rc.amount),
        'category': rc.category,
        'description': rc.description,
        'day_of_month': rc.day_of_month,
        'is_active': rc.is_active,
        'created_at': rc.created_at.isoformat(),
    }

@bp.route('/recurring-charges', methods=['GET'])
@login_required
def get_recurring_charges():
    """Get all recurring charge rules"""
    charges = RecurringCharge.query.order_by(RecurringCharge.created_at).all()
    return jsonify({'recurring_charges': [recurring_to_dict(rc) for rc in charges]})

@bp.route('/recurring-charges', methods=['POST'])
@login_required
def create_recurring_charge():
    """Create a new recurring charge rule"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    for field in ['class_id', 'amount', 'category']:
        if not data.get(field):
            return jsonify({'error': f'{field} is required'}), 400

    dance_class = DanceClass.query.get(data['class_id'])
    if not dance_class:
        return jsonify({'error': 'Class not found'}), 404

    day = int(data.get('day_of_month', 1))
    if day < 1 or day > 28:
        return jsonify({'error': 'day_of_month must be 1-28'}), 400

    rc = RecurringCharge(
        class_id=dance_class.id,
        amount=data['amount'],
        category=data['category'],
        description=data.get('description', '').strip() or None,
        day_of_month=day,
        created_by=current_user.id,
    )
    db.session.add(rc)
    db.session.commit()
    return jsonify(recurring_to_dict(rc)), 201

@bp.route('/recurring-charges/<int:rc_id>', methods=['DELETE'])
@login_required
def delete_recurring_charge(rc_id):
    """Deactivate a recurring charge"""
    rc = RecurringCharge.query.get_or_404(rc_id)
    rc.is_active = False
    db.session.commit()
    return jsonify({'message': 'Recurring charge deactivated'})

@bp.route('/recurring-charges/process', methods=['POST'])
@login_required
def process_recurring_charges():
    """Manually trigger recurring charge processing"""
    from app import _process_recurring_charges
    _process_recurring_charges()
    return jsonify({'message': 'Recurring charges processed'})

# Square payment endpoints
@bp.route('/square/status', methods=['GET'])
@login_required
def square_status():
    """Check if Square is configured"""
    return jsonify({'configured': square_service.is_configured()})

@bp.route('/students/<int:student_id>/send-invoice', methods=['POST'])
@login_required
def send_student_invoice(student_id):
    """Send a Square invoice for a student's outstanding balance"""
    if not square_service.is_configured():
        return jsonify({'error': 'Square is not configured. Set SQUARE_ACCESS_TOKEN and SQUARE_LOCATION_ID in environment.'}), 400

    student = Student.query.get_or_404(student_id)
    txns = Transaction.query.filter_by(student_id=student_id).all()
    total_charges = sum(float(t.amount) for t in txns if (t.type or 'payment') == 'charge')
    total_payments = sum(float(t.amount) for t in txns if (t.type or 'payment') == 'payment')
    balance = total_charges - total_payments

    if balance <= 0:
        return jsonify({'error': 'No outstanding balance to invoice'}), 400

    # Build line items from unpaid charges
    unpaid_charges = [t for t in txns if (t.type or 'payment') == 'charge']
    line_items = []
    for t in unpaid_charges:
        line_items.append({
            'name': t.description or t.category,
            'amount_cents': int(float(t.amount) * 100),
        })

    # Due in 14 days
    due = date.today() + timedelta(days=14)

    try:
        result = square_service.send_invoice(
            student=student,
            amount_cents=int(balance * 100),
            line_items=line_items,
            due_date=due,
        )
        return jsonify({
            'message': f'Invoice sent to {student.parent_email or student.email}',
            'invoice_url': result['invoice_url'],
            'invoice_id': result['invoice_id'],
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Parent invite endpoints
@bp.route('/students/<int:student_id>/invite-parent', methods=['POST'])
@login_required
def invite_parent(student_id):
    """Generate an invite code for a student's parent"""
    if (current_user.role or 'teacher') == 'parent':
        return jsonify({'error': 'Only staff can generate invites'}), 403

    student = Student.query.get_or_404(student_id)

    # Check if there's already a pending invite for this student
    existing_links = ParentStudent.query.filter_by(student_id=student_id).all()
    for link in existing_links:
        parent = User.query.get(link.parent_id)
        if parent and parent.is_active:
            return jsonify({'error': f'Parent already linked: {parent.full_name} ({parent.email})'}), 400

    # Generate invite code
    code = secrets.token_hex(4).upper()  # 8-char hex code

    # Create inactive parent user placeholder
    placeholder_email = f'invite-{code}@pending.local'
    parent_user = User(
        username=f'parent-{code}',
        email=placeholder_email,
        first_name='Pending',
        last_name='Parent',
        password_hash='not-set',
        role='parent',
        is_active=False,
        invite_code=code,
    )
    db.session.add(parent_user)
    db.session.flush()

    # Link to student
    link = ParentStudent(parent_id=parent_user.id, student_id=student_id)
    db.session.add(link)
    db.session.commit()

@bp.route('/seed-demo-parent', methods=['POST'])
@login_required
def seed_demo_parent():
    """Create a demo parent account for testing"""
    student = Student.query.first()
    if not student:
        return jsonify({'error': 'No students found'}), 400
    existing = User.query.filter_by(username='parent-demo').first()
    if existing:
        ParentStudent.query.filter_by(parent_id=existing.id).delete()
        db.session.delete(existing)
        db.session.commit()
    p = User(username='parent-demo', email='parent@demo.local',
             first_name='Demo', last_name='Parent', role='parent', is_active=True)
    p.set_password('parent123')
    db.session.add(p)
    db.session.flush()
    db.session.add(ParentStudent(parent_id=p.id, student_id=student.id))
    db.session.commit()
    return jsonify({'message': f'Parent account created: parent-demo / parent123, linked to {student.full_name}'})

    return jsonify({
        'invite_code': code,
        'message': f'Invite code generated for {student.full_name}. Share this with the parent: {code}',
        'register_url': f'/auth/register?code={code}',
    }), 201

# Rules & Regulations endpoints
@bp.route('/rules', methods=['GET'])
@login_required
def get_rules():
    """Get all active rules"""
    rules = Rule.query.filter_by(is_active=True).order_by(Rule.display_order).all()
    return jsonify({'rules': [{
        'id': r.id, 'text': r.text, 'display_order': r.display_order,
    } for r in rules]})

@bp.route('/rules', methods=['POST'])
@login_required
def create_rule():
    """Create a new rule (admin only)"""
    data = request.get_json()
    if not data or not data.get('text'):
        return jsonify({'error': 'text is required'}), 400
    max_order = db.session.query(func.max(Rule.display_order)).scalar() or 0
    r = Rule(text=data['text'].strip(), display_order=max_order + 1)
    db.session.add(r)
    db.session.commit()
    return jsonify({'id': r.id, 'text': r.text, 'display_order': r.display_order}), 201

@bp.route('/rules/<int:rule_id>', methods=['PUT'])
@login_required
def update_rule(rule_id):
    """Update a rule's text"""
    r = Rule.query.get_or_404(rule_id)
    data = request.get_json()
    if data.get('text'):
        r.text = data['text'].strip()
    if 'display_order' in data:
        r.display_order = int(data['display_order'])
    db.session.commit()
    return jsonify({'id': r.id, 'text': r.text, 'display_order': r.display_order})

@bp.route('/rules/<int:rule_id>', methods=['DELETE'])
@login_required
def delete_rule(rule_id):
    """Deactivate a rule"""
    r = Rule.query.get_or_404(rule_id)
    r.is_active = False
    db.session.commit()
    return jsonify({'message': 'Rule removed'})

@bp.route('/students/<int:student_id>/rules-status', methods=['GET'])
@login_required
def get_student_rules_status(student_id):
    """Get which rules a student's parent has acknowledged"""
    student = Student.query.get_or_404(student_id)
    rules = Rule.query.filter_by(is_active=True).order_by(Rule.display_order).all()
    acks = RuleAcknowledgment.query.filter_by(student_id=student_id).all()
    acked_rule_ids = {a.rule_id for a in acks}
    ack_map = {a.rule_id: a for a in acks}
    result = []
    for r in rules:
        ack = ack_map.get(r.id)
        result.append({
            'rule_id': r.id, 'text': r.text, 'display_order': r.display_order,
            'acknowledged': r.id in acked_rule_ids,
            'initials': ack.initials if ack else None,
            'acknowledged_at': ack.acknowledged_at.isoformat() if ack else None,
        })
    total = len(rules)
    done = len(acked_rule_ids & {r.id for r in rules})
    return jsonify({
        'student_name': student.full_name,
        'rules': result,
        'total': total, 'acknowledged': done,
        'complete': done == total and total > 0,
    })

@bp.route('/rules/<int:rule_id>/acknowledge', methods=['POST'])
@login_required
def acknowledge_rule(rule_id):
    """Parent initials a specific rule for a student"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    student_id = data.get('student_id')
    initials = data.get('initials', '').strip()
    if not student_id or not initials:
        return jsonify({'error': 'student_id and initials are required'}), 400
    rule = Rule.query.get_or_404(rule_id)
    student = Student.query.get_or_404(student_id)
    existing = RuleAcknowledgment.query.filter_by(
        rule_id=rule_id, student_id=student_id, parent_id=current_user.id
    ).first()
    if existing:
        return jsonify({'message': 'Already acknowledged'}), 200
    ack = RuleAcknowledgment(
        rule_id=rule_id, student_id=student_id,
        parent_id=current_user.id, initials=initials.upper(),
    )
    db.session.add(ack)
    db.session.commit()
    return jsonify({'message': 'Rule acknowledged', 'initials': ack.initials}), 201

# Message / Email blast endpoints
@bp.route('/messages', methods=['GET'])
@login_required
def get_messages():
    """Get message history"""
    msgs = Message.query.order_by(desc(Message.created_at)).limit(50).all()
    return jsonify({'messages': [{
        'id': m.id, 'subject': m.subject, 'body': m.body,
        'recipient_type': m.recipient_type, 'recipient_filter': m.recipient_filter,
        'recipient_count': m.recipient_count, 'recipient_emails': m.recipient_emails,
        'sent': m.sent, 'sent_at': m.sent_at.isoformat() if m.sent_at else None,
        'created_by': m.creator.full_name if m.creator else None,
        'created_at': m.created_at.isoformat(),
    } for m in msgs]})

@bp.route('/messages', methods=['POST'])
@login_required
def send_message():
    """Compose and send an email blast"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    for field in ['subject', 'body', 'recipient_type']:
        if not data.get(field):
            return jsonify({'error': f'{field} is required'}), 400

    # Resolve recipient emails
    rtype = data['recipient_type']
    emails = set()
    if rtype == 'all':
        for s in Student.query.filter_by(is_active=True).all():
            if s.parent_email:
                emails.add(s.parent_email)
            elif s.email:
                emails.add(s.email)
    elif rtype == 'class':
        class_id = data.get('recipient_filter')
        if not class_id:
            return jsonify({'error': 'recipient_filter (class_id) required for class type'}), 400
        enrollments = ClassEnrollment.query.filter_by(class_id=int(class_id), is_active=True).all()
        for e in enrollments:
            s = Student.query.get(e.student_id)
            if s and (s.parent_email or s.email):
                emails.add(s.parent_email or s.email)
    elif rtype == 'individual':
        student_id = data.get('recipient_filter')
        if not student_id:
            return jsonify({'error': 'recipient_filter (student_id) required for individual type'}), 400
        s = Student.query.get(int(student_id))
        if s and (s.parent_email or s.email):
            emails.add(s.parent_email or s.email)

    if not emails:
        return jsonify({'error': 'No email addresses found for selected recipients'}), 400

    # Save message
    msg = Message(
        subject=data['subject'].strip(),
        body=data['body'].strip(),
        recipient_type=rtype,
        recipient_filter=str(data.get('recipient_filter', '')),
        recipient_count=len(emails),
        recipient_emails=', '.join(sorted(emails)),
        created_by=current_user.id,
    )

    # Try to send via SMTP
    mail_server = current_app.config.get('MAIL_SERVER')
    if mail_server:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        try:
            smtp = smtplib.SMTP(mail_server, current_app.config.get('MAIL_PORT', 587))
            if current_app.config.get('MAIL_USE_TLS', True):
                smtp.starttls()
            username = current_app.config.get('MAIL_USERNAME')
            password = current_app.config.get('MAIL_PASSWORD')
            if username and password:
                smtp.login(username, password)
            for email in emails:
                m = MIMEMultipart()
                m['From'] = username or 'noreply@attenddance.local'
                m['To'] = email
                m['Subject'] = data['subject'].strip()
                m.attach(MIMEText(data['body'].strip(), 'plain'))
                smtp.sendmail(m['From'], email, m.as_string())
            smtp.quit()
            msg.sent = True
            msg.sent_at = datetime.utcnow()
        except Exception as e:
            msg.sent = False
            db.session.add(msg)
            db.session.commit()
            return jsonify({
                'error': f'SMTP send failed: {e}',
                'message_id': msg.id,
                'recipient_emails': sorted(emails),
                'saved': True,
            }), 500
    else:
        msg.sent = False

    db.session.add(msg)
    db.session.commit()

    if msg.sent:
        return jsonify({'message': f'Email sent to {len(emails)} recipient(s)', 'message_id': msg.id}), 201
    else:
        return jsonify({
            'message': f'Message saved (SMTP not configured — copy emails below to send manually)',
            'message_id': msg.id,
            'recipient_emails': sorted(emails),
            'recipient_count': len(emails),
        }), 201

# Family endpoints
@bp.route('/families', methods=['GET'])
@login_required
def get_families():
    """Get all families"""
    families = Family.query.filter_by(is_active=True).order_by(Family.name).all()
    result = []
    for f in families:
        students = f.students.filter_by(is_active=True).all()
        all_txns = []
        for s in students:
            all_txns.extend(Transaction.query.filter_by(student_id=s.id).all())
        total_charges = sum(float(t.amount) for t in all_txns if (t.type or 'payment') == 'charge')
        total_payments = sum(float(t.amount) for t in all_txns if (t.type or 'payment') == 'payment')
        result.append({
            'id': f.id, 'name': f.name,
            'primary_email': f.primary_email, 'primary_phone': f.primary_phone,
            'student_count': len(students),
            'students': [{'id': s.id, 'full_name': s.full_name} for s in students],
            'total_charges': f'{total_charges:.2f}',
            'total_payments': f'{total_payments:.2f}',
            'balance': f'{total_charges - total_payments:.2f}',
        })
    return jsonify({'families': result})

@bp.route('/families', methods=['POST'])
@login_required
def create_family():
    """Create a new family"""
    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({'error': 'name is required'}), 400
    f = Family(
        name=data['name'].strip(),
        primary_email=data.get('primary_email', '').strip() or None,
        primary_phone=data.get('primary_phone', '').strip() or None,
    )
    db.session.add(f)
    db.session.commit()
    return jsonify({'id': f.id, 'name': f.name}), 201

@bp.route('/families/<int:family_id>/ledger', methods=['GET'])
@login_required
def get_family_ledger(family_id):
    """Get combined ledger for all students in a family"""
    family = Family.query.get_or_404(family_id)
    students = family.students.filter_by(is_active=True).all()
    all_txns = []
    for s in students:
        all_txns.extend(Transaction.query.filter_by(student_id=s.id).all())
    all_txns.sort(key=lambda t: (t.transaction_date, t.created_at))
    running = 0.0
    ledger = []
    for t in all_txns:
        amt = float(t.amount)
        if (t.type or 'payment') == 'charge':
            running += amt
        else:
            running -= amt
        ledger.append({**transaction_to_dict(t), 'running_balance': f'{running:.2f}'})
    total_charges = sum(float(t.amount) for t in all_txns if (t.type or 'payment') == 'charge')
    total_payments = sum(float(t.amount) for t in all_txns if (t.type or 'payment') == 'payment')
    return jsonify({
        'family_id': family.id, 'family_name': family.name,
        'students': [{'id': s.id, 'full_name': s.full_name} for s in students],
        'ledger': ledger,
        'total_charges': f'{total_charges:.2f}',
        'total_payments': f'{total_payments:.2f}',
        'balance': f'{total_charges - total_payments:.2f}',
    })