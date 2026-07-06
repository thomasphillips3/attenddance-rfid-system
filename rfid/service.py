"""
RFID Background Service for automatic attendance processing
"""

import logging
import time
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.exc import IntegrityError

from rfid.reader import create_rfid_reader
from app.models import Student, Attendance, DanceClass, RFIDLog
from app import db

# Setup logging
logger = logging.getLogger(__name__)

class RFIDService:
    """Background service for processing RFID card scans"""
    
    def __init__(self):
        """Initialize RFID service"""
        self.reader = None
        self._app = None
        self.running = False
        self.scan_interval = 0.5  # seconds between scans
        self.last_scan_uid = None
        self.last_scan_time = None
        self.duplicate_scan_window = 5  # seconds to ignore duplicate scans
        
        # Statistics
        self.total_scans = 0
        self.successful_checkins = 0
        self.failed_scans = 0
        
        logger.info("RFID service initialized")
    
    def start_listening(self):
        """Start the RFID listening service"""
        try:
            # Initialize RFID reader
            self.reader = create_rfid_reader()
            logger.info("RFID service starting...")
            
            self.running = True
            
            while self.running:
                try:
                    self._scan_for_cards()
                    time.sleep(self.scan_interval)
                except KeyboardInterrupt:
                    logger.info("RFID service interrupted by user")
                    break
                except Exception as e:
                    logger.error(f"Error in RFID service: {e}")
                    time.sleep(1)  # Wait before retrying
                    
        except Exception as e:
            logger.error(f"Failed to start RFID service: {e}")
        finally:
            self._cleanup()
    
    def stop_listening(self):
        """Stop the RFID listening service"""
        logger.info("Stopping RFID service...")
        self.running = False

    def _get_app(self):
        """Reuse ONE Flask app across scans. create_app() runs migrations, seeds
        the admin, and kicks off startup jobs (recurring charges, reminder
        threads) — calling it per card tap (as this did) re-ran all of that on
        every scan and spawned a daemon thread each time, a slow resource leak
        over a day of scanning. Build it once, lazily, and reuse it."""
        if self._app is None:
            from app import create_app
            self._app = create_app()
        return self._app
    
    def _scan_for_cards(self):
        """Scan for RFID cards and process them"""
        try:
            # Try to read a card with short timeout
            result = self.reader.read_card(timeout=0.1)
            
            if result:
                uid, text = result
                self.total_scans += 1
                
                # Check for duplicate scans
                if self._is_duplicate_scan(uid):
                    logger.debug(f"Ignoring duplicate scan: {uid}")
                    return
                
                logger.info(f"Processing RFID scan: UID={uid}")
                success = self._process_card_scan(uid, text)
                
                if success:
                    self.successful_checkins += 1
                else:
                    self.failed_scans += 1
                
                # Update last scan info
                self.last_scan_uid = uid
                self.last_scan_time = datetime.utcnow()
                
        except Exception as e:
            logger.error(f"Error scanning for cards: {e}")
    
    def _is_duplicate_scan(self, uid: str) -> bool:
        """Check if this is a duplicate scan within the time window"""
        if (self.last_scan_uid == uid and 
            self.last_scan_time and 
            (datetime.utcnow() - self.last_scan_time).total_seconds() < self.duplicate_scan_window):
            return True
        return False
    
    def _process_card_scan(self, uid: str, text: str = "") -> bool:
        """
        Process an RFID card scan
        
        Args:
            uid: Card UID
            text: Card text content
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Reuse the cached app (see _get_app) instead of building one per scan.
            app = self._get_app()

            with app.app_context():
                # Log the scan
                self._log_rfid_scan(uid, "processing")
                
                # Find student by RFID UID
                student = Student.query.filter_by(rfid_uid=uid, is_active=True).first()
                
                if not student:
                    logger.warning(f"Unknown RFID card: {uid}")
                    self._log_rfid_scan(uid, "unknown_card", success=False, 
                                      error="Student not found for RFID UID")
                    return False
                
                # Find current class for check-in
                current_class = self._find_current_class(student)
                
                if not current_class:
                    logger.warning(f"No current class found for student #{student.id}")
                    self._log_rfid_scan(uid, "no_class", success=False, 
                                      error="No current class found", student_id=student.id)
                    return False
                
                # Check if already checked in today
                today = date.today()
                existing_attendance = Attendance.query.filter(
                    Attendance.student_id == student.id,
                    Attendance.class_id == current_class.id,
                    db.func.date(Attendance.check_in_time) == today
                ).first()
                
                if existing_attendance:
                    logger.info(f"Student #{student.id} already checked in today")
                    self._log_rfid_scan(uid, "already_checked_in", success=True, 
                                      error="Already checked in today", student_id=student.id)
                    return True
                
                # Create attendance record. Local time (server runs in the studio
                # timezone) so the date matches the `date.today()` used in the
                # duplicate check above and the unique-day index — datetime.utcnow()
                # would date an evening scan on the next UTC day, hiding it from
                # today's roster. Same basis as the manual/toggle check-in paths.
                attendance = Attendance(
                    student_id=student.id,
                    class_id=current_class.id,
                    check_in_time=datetime.now(),
                    check_in_method='rfid',
                    is_present=True
                )

                db.session.add(attendance)
                try:
                    db.session.commit()
                except IntegrityError:
                    # A near-simultaneous scan (past the existing-check above) hit
                    # the unique (student, class, day) index. The student is
                    # already marked present — recover the session and treat it as
                    # an already-checked-in success rather than wedging the reader.
                    db.session.rollback()
                    self._log_rfid_scan(uid, "already_checked_in", success=True,
                                        error="Already checked in today", student_id=student.id)
                    return True

                logger.info(f"✅ Student #{student.id} checked in to {current_class.name}")
                self._log_rfid_scan(uid, "checkin", success=True, student_id=student.id)

                return True
                
        except Exception as e:
            logger.error(f"Error processing card scan: {e}")
            self._log_rfid_scan(uid, "error", success=False, error=str(e))
            return False
    
    def _find_current_class(self, student: Student) -> Optional[DanceClass]:
        """
        Find the current class for a student based on schedule and enrollment
        
        Args:
            student: Student object
            
        Returns:
            DanceClass if found, None otherwise
        """
        try:
            now = datetime.now()
            current_time = now.time()
            current_weekday = now.weekday()  # 0=Monday, 6=Sunday
            
            # Get student's enrolled classes
            enrolled_classes = [enrollment.dance_class for enrollment in 
                              student.class_enrollments.filter_by(is_active=True).all()]
            
            if not enrolled_classes:
                return None
            
            # Find class that matches current day and time
            for dance_class in enrolled_classes:
                if not dance_class.is_active:
                    continue
                
                # Check if today is the class day
                if dance_class.day_of_week != current_weekday:
                    continue
                
                # Check if current time is within class time window (with some buffer)
                class_start = dance_class.start_time
                class_end = dance_class.end_time
                
                start_buffer = (datetime.combine(date.today(), class_start) -
                                timedelta(minutes=30)).time()
                end_buffer = (datetime.combine(date.today(), class_end) +
                              timedelta(minutes=15)).time()
                
                if start_buffer <= current_time <= end_buffer:
                    return dance_class
            
            # If no exact match, return the first enrolled class for today
            for dance_class in enrolled_classes:
                if dance_class.is_active and dance_class.day_of_week == current_weekday:
                    return dance_class
            
            # No class found for today
            return None
            
        except Exception as e:
            logger.error(f"Error finding current class: {e}")
            return None
    
    def _log_rfid_scan(self, uid: str, action: str, success: bool = True, 
                      error: str = None, student_id: int = None):
        """Log RFID scan to database"""
        try:
            app = self._get_app()

            with app.app_context():
                log_entry = RFIDLog(
                    rfid_uid=uid,
                    student_id=student_id,
                    scan_time=datetime.now(),  # studio-local, like the check-in it logs
                    action_taken=action,
                    success=success,
                    error_message=error
                )
                
                db.session.add(log_entry)
                db.session.commit()
                
        except Exception as e:
            logger.error(f"Failed to log RFID scan: {e}")
    
    def _cleanup(self):
        """Cleanup resources"""
        self.running = False
        if self.reader:
            try:
                self.reader.cleanup()
            except Exception:
                pass
        
        logger.info(f"RFID service stopped. Stats: Total scans: {self.total_scans}, "
                   f"Successful check-ins: {self.successful_checkins}, "
                   f"Failed scans: {self.failed_scans}")
    
    def get_stats(self) -> dict:
        """Get service statistics"""
        return {
            'running': self.running,
            'total_scans': self.total_scans,
            'successful_checkins': self.successful_checkins,
            'failed_scans': self.failed_scans,
            'last_scan_time': self.last_scan_time,
            'last_scan_uid': self.last_scan_uid
        }
    
    def simulate_scan(self, uid: str) -> bool:
        """
        Simulate a card scan (for testing)
        
        Args:
            uid: UID to simulate
            
        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Simulating RFID scan: {uid}")
        return self._process_card_scan(uid, "")

# Global service instance
rfid_service_instance = None

def get_rfid_service() -> RFIDService:
    """Get global RFID service instance"""
    global rfid_service_instance
    if rfid_service_instance is None:
        rfid_service_instance = RFIDService()
    return rfid_service_instance 