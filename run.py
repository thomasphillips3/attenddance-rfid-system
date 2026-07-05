#!/usr/bin/env python3
"""AttenDANCE - RFID Attendance System — main entry point."""

import logging
import os
import threading

# Configure logging at import time so it applies under BOTH gunicorn (which
# imports `run:app`, so __main__ never runs) and the dev server. Without this,
# production silently drops every INFO log — the operator can't confirm from the
# logs that the automated engines ran (recurring charges, auto-reminders) or that
# the app booted. basicConfig is a no-op if the root logger is already configured.
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

from app import create_app  # noqa: E402 — after logging setup so boot logs are captured

logger = logging.getLogger(__name__)

# Module-level app for gunicorn (gunicorn run:app)
app = create_app()


def main():
    """Run the dev server with optional RFID service."""
    if not app.config.get('TESTING', False):
        try:
            from rfid.service import RFIDService
            rfid_service = RFIDService()
            rfid_thread = threading.Thread(
                target=rfid_service.start_listening,
                daemon=True,
                name="RFID-Service",
            )
            rfid_thread.start()
            logger.info("RFID service started successfully")
        except Exception:
            logger.info("RFID service not available (normal on non-Raspberry Pi hardware)")

    host = os.environ.get('FLASK_HOST', '0.0.0.0')
    # Honor PORT (12-factor / PaaS / preview harness) first, then FLASK_PORT.
    port = int(os.environ.get('PORT') or os.environ.get('FLASK_PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'

    logger.info("AttenDANCE starting on http://%s:%d (debug=%s)", host, port, debug)

    app.run(
        host=host,
        port=port,
        debug=debug,
        use_reloader=False,
    )


if __name__ == '__main__':
    main()
