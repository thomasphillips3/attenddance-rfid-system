# AttenDANCE - RFID Attendance System

A complete RFID-based attendance system for dance studios running on Raspberry Pi.

## Features

- 🎯 **RFID Check-in**: Students tap RFID cards to check in before classes
- 👨‍🏫 **Teacher Dashboard**: Web interface for viewing attendance and managing students
- 📱 **Responsive Design**: Mobile-first design that works on all devices
- 🔄 **Progressive Web App**: Installable PWA with offline capabilities
- 🗄️ **Local Storage**: SQLite database for reliable local data storage
- 🔐 **Authentication**: Secure teacher login system
- 🎨 **Modern UI**: Clean, intuitive interface built with Tailwind CSS

## Hardware Requirements

- Raspberry Pi 4 (recommended) running Ubuntu
- MFRC522 RFID module connected via SPI
- RFID cards/tags for students
- Optional: Touchscreen display for kiosk mode

## Quick Start

### 1. Hardware Setup
Connect your MFRC522 RFID module to the Raspberry Pi:
- SDA → Pin 24 (GPIO 8, CE0)
- SCK → Pin 23 (GPIO 11, SCLK)
- MOSI → Pin 19 (GPIO 10, MOSI)
- MISO → Pin 21 (GPIO 9, MISO)
- IRQ → Not connected
- GND → Pin 6 (Ground)
- RST → Pin 22 (GPIO 25)
- 3.3V → Pin 1 (3.3V)

### 2. Software Installation
```bash
# Clone the repository
git clone <your-repo-url>
cd attendance-system

# Run the installation script
sudo chmod +x scripts/install.sh
sudo ./scripts/install.sh

# Initialize the database
python scripts/init_db.py

# Create admin user
python scripts/create_admin.py
```

### 3. Running the Application

#### Development Mode
```bash
python run.py
```
Access the web interface at `http://localhost:5000`

#### Production Mode
```bash
# Install as systemd service
sudo ./scripts/setup_service.sh

# Start the service
sudo systemctl start attenddance
sudo systemctl enable attenddance
```

## Project Structure

```
attendance-system/
├── app/                    # Flask application
│   ├── __init__.py
│   ├── models.py          # Database models
│   ├── auth/              # Authentication routes
│   ├── api/               # REST API routes
│   ├── templates/         # HTML templates
│   └── static/            # CSS, JS, images
├── rfid/                  # RFID module code
│   ├── __init__.py
│   ├── reader.py          # RFID reading logic
│   └── service.py         # Background RFID service
├── scripts/               # Installation and setup scripts
├── config/                # Configuration files
├── requirements.txt       # Python dependencies
├── run.py                # Application entry point
└── README.md
```

## API Endpoints

### Authentication
- `POST /api/auth/login` - Teacher login
- `POST /api/auth/logout` - Logout
- `GET /api/auth/me` - Get current user info

### Students
- `GET /api/students` - List all students
- `POST /api/students` - Add new student
- `PUT /api/students/<id>` - Update student
- `DELETE /api/students/<id>` - Remove student
- `POST /api/students/<id>/assign-rfid` - Assign RFID card

### Attendance
- `GET /api/attendance` - Get attendance records
- `POST /api/attendance/checkin` - Manual check-in
- `GET /api/attendance/today` - Today's attendance

### Classes
- `GET /api/classes` - List classes
- `POST /api/classes` - Create class
- `PUT /api/classes/<id>` - Update class

## Configuration

Edit `config/config.py` to customize:
- Database path
- Secret keys
- RFID settings
- Server settings

## Troubleshooting

### RFID Not Working
1. Check SPI is enabled: `sudo raspi-config` → Interface Options → SPI → Enable
2. Verify wiring connections
3. Test with: `python scripts/test_rfid.py`

### Database Issues
- Reset database: `python scripts/reset_db.py`
- Backup database: `cp data/attendance.db data/attendance_backup.db`

### Service Issues
- Check status: `sudo systemctl status attenddance`
- View logs: `sudo journalctl -u attenddance -f`

## License

MIT License - See LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## Support

For issues and questions, please open a GitHub issue or contact the development team. 