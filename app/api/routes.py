"""
REST API routes for AttenDANCE system
"""

from datetime import datetime, date, timedelta
from flask import request, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import and_, or_, desc, func

from app.api import bp
from app.models import User, Student, DanceClass, ClassEnrollment, Attendance, RFIDLog
from app import db
from rfid.service import get_rfid_service

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
    
    required_fields = ['name', 'day_of_week', 'start_time', 'end_time', 'instructor_id']
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
            instructor_id=int(data['instructor_id']),
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