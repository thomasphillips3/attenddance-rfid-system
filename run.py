#!/usr/bin/env python3
"""
AttenDANCE - RFID Attendance System
Main application entry point
"""

import os
import sys
import threading
from app import create_app
from config.config import Config
from rfid.service import RFIDService

def main():
    """Main application entry point"""
    # Create Flask app
    app = create_app()
    
    # Start RFID service in background thread if not in testing mode
    if not app.config.get('TESTING', False):
        try:
            rfid_service = RFIDService()
            rfid_thread = threading.Thread(
                target=rfid_service.start_listening,
                daemon=True,
                name="RFID-Service"
            )
            rfid_thread.start()
            print("✅ RFID service started successfully")
        except Exception as e:
            print(f"⚠️  Warning: Could not start RFID service: {e}")
            print("   This is normal if running on non-Raspberry Pi hardware")
    
    # Get configuration
    host = os.environ.get('FLASK_HOST', '0.0.0.0')
    port = int(os.environ.get('FLASK_PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    
    print(f"🎭 AttenDANCE starting on http://{host}:{port}")
    print(f"   Debug mode: {debug}")
    print(f"   Database: {app.config['SQLALCHEMY_DATABASE_URI']}")
    
    # Run the application
    app.run(
        host=host,
        port=port,
        debug=debug,
        use_reloader=False  # Disable reloader to prevent RFID service conflicts
    )

if __name__ == '__main__':
    main() 