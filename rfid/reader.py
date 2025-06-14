"""
RFID Reader implementation for MFRC522 module
"""

import time
import logging
from typing import Optional, Tuple

# Setup logging
logger = logging.getLogger(__name__)

class RFIDReader:
    """RFID Reader class for MFRC522 module"""
    
    def __init__(self, spi_dev=0, rst_pin=25):
        """
        Initialize RFID reader
        
        Args:
            spi_dev: SPI device number (default: 0)
            rst_pin: Reset pin number (default: 25)
        """
        self.spi_dev = spi_dev
        self.rst_pin = rst_pin
        self.reader = None
        self.is_initialized = False
        
        try:
            self._initialize_reader()
        except Exception as e:
            logger.warning(f"Failed to initialize RFID reader: {e}")
            logger.info("This is normal if not running on Raspberry Pi hardware")
    
    def _initialize_reader(self):
        """Initialize the MFRC522 reader"""
        try:
            # Import MFRC522 library (only available on Raspberry Pi)
            from mfrc522 import SimpleMFRC522
            import RPi.GPIO as GPIO
            
            # Set GPIO warnings off (optional)
            GPIO.setwarnings(False)
            
            # Initialize the reader
            self.reader = SimpleMFRC522()
            self.is_initialized = True
            logger.info("RFID reader initialized successfully")
            
        except ImportError as e:
            logger.warning("MFRC522 library not available - running in mock mode")
            raise e
        except Exception as e:
            logger.error(f"Failed to initialize RFID reader: {e}")
            raise e
    
    def read_card(self, timeout=None) -> Optional[Tuple[str, str]]:
        """
        Read RFID card
        
        Args:
            timeout: Read timeout in seconds (None for blocking read)
            
        Returns:
            Tuple of (uid, text) if card read successfully, None otherwise
        """
        if not self.is_initialized:
            logger.warning("RFID reader not initialized")
            return None
        
        try:
            logger.debug("Waiting for RFID card...")
            
            if timeout:
                # Non-blocking read with timeout
                start_time = time.time()
                while time.time() - start_time < timeout:
                    try:
                        # Try to read card (non-blocking)
                        uid, text = self.reader.read_no_block()
                        if uid:
                            uid_str = str(uid)
                            text_str = text.strip() if text else ""
                            logger.info(f"RFID card read: UID={uid_str}")
                            return (uid_str, text_str)
                    except:
                        pass
                    time.sleep(0.1)
                
                logger.debug("RFID read timeout")
                return None
            else:
                # Blocking read
                uid, text = self.reader.read()
                uid_str = str(uid)
                text_str = text.strip() if text else ""
                logger.info(f"RFID card read: UID={uid_str}")
                return (uid_str, text_str)
                
        except Exception as e:
            logger.error(f"Error reading RFID card: {e}")
            return None
    
    def write_card(self, text: str, uid: str = None) -> bool:
        """
        Write text to RFID card
        
        Args:
            text: Text to write to card
            uid: Optional UID to verify (not used in SimpleMFRC522)
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_initialized:
            logger.warning("RFID reader not initialized")
            return False
        
        try:
            logger.info(f"Writing to RFID card: {text}")
            self.reader.write(text)
            logger.info("RFID card written successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error writing RFID card: {e}")
            return False
    
    def read_uid_only(self, timeout=None) -> Optional[str]:
        """
        Read only the UID from RFID card
        
        Args:
            timeout: Read timeout in seconds
            
        Returns:
            UID string if successful, None otherwise
        """
        result = self.read_card(timeout)
        if result:
            return result[0]
        return None
    
    def is_card_present(self) -> bool:
        """
        Check if a card is present (non-blocking)
        
        Returns:
            True if card is present, False otherwise
        """
        if not self.is_initialized:
            return False
        
        try:
            # Try a quick non-blocking read
            result = self.read_card(timeout=0.1)
            return result is not None
        except:
            return False
    
    def cleanup(self):
        """Cleanup GPIO resources"""
        if self.is_initialized:
            try:
                import RPi.GPIO as GPIO
                GPIO.cleanup()
                logger.info("RFID reader cleanup completed")
            except:
                pass

class MockRFIDReader(RFIDReader):
    """Mock RFID reader for testing and non-Raspberry Pi environments"""
    
    def __init__(self, spi_dev=0, rst_pin=25):
        """Initialize mock reader"""
        self.spi_dev = spi_dev
        self.rst_pin = rst_pin
        self.reader = None
        self.is_initialized = True
        self.mock_cards = {
            "123456789": "Student Test Card",
            "987654321": "Teacher Test Card",
            "555666777": "Demo Card"
        }
        logger.info("Mock RFID reader initialized")
    
    def read_card(self, timeout=None) -> Optional[Tuple[str, str]]:
        """Simulate reading an RFID card"""
        # In a real mock, you might want to simulate user input
        # For now, we'll just return None to indicate no card
        logger.debug("Mock RFID reader - no card simulation")
        return None
    
    def simulate_card_scan(self, uid: str) -> Optional[Tuple[str, str]]:
        """
        Simulate scanning a specific card (for testing)
        
        Args:
            uid: UID to simulate
            
        Returns:
            Tuple of (uid, text) if card exists in mock data
        """
        if uid in self.mock_cards:
            text = self.mock_cards[uid]
            logger.info(f"Mock RFID scan: UID={uid}, Text={text}")
            return (uid, text)
        else:
            logger.info(f"Mock RFID scan: Unknown card UID={uid}")
            return (uid, "")
    
    def write_card(self, text: str, uid: str = None) -> bool:
        """Simulate writing to RFID card"""
        logger.info(f"Mock RFID write: {text}")
        return True
    
    def cleanup(self):
        """Mock cleanup"""
        logger.info("Mock RFID reader cleanup completed")

def create_rfid_reader(spi_dev=0, rst_pin=25, force_mock=False) -> RFIDReader:
    """
    Factory function to create appropriate RFID reader
    
    Args:
        spi_dev: SPI device number
        rst_pin: Reset pin number
        force_mock: Force use of mock reader
        
    Returns:
        RFIDReader instance (real or mock)
    """
    if force_mock:
        return MockRFIDReader(spi_dev, rst_pin)
    
    try:
        # Try to create real reader
        reader = RFIDReader(spi_dev, rst_pin)
        if reader.is_initialized:
            return reader
        else:
            logger.info("Falling back to mock RFID reader")
            return MockRFIDReader(spi_dev, rst_pin)
    except:
        logger.info("Creating mock RFID reader")
        return MockRFIDReader(spi_dev, rst_pin) 