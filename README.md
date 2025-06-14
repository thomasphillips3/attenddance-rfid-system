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
git clone https://github.com/thomasphillips3/attenddance-rfid-system.git
cd attenddance-rfid-system

# Create virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Enable SPI on Raspberry Pi (if not already enabled)
sudo raspi-config
# Navigate to: Interface Options → SPI → Enable
```

### 3. Running the Application

#### Development Mode
```bash
python run.py
```
Access the web interface at `http://localhost:5000`

**Default Login:**
- Username: `admin`
- Password: `admin123`

*⚠️ Change the default password immediately after first login!*

#### Production Mode
```bash
# Set production environment
export FLASK_ENV=production
export SECRET_KEY=your-secret-key-here

# Run with Gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 run:app

# Or run as background process
nohup python run.py > attendance.log 2>&1 &
```

#### Optional: System Service Setup
Create a systemd service for automatic startup:

```bash
# Create service file
sudo nano /etc/systemd/system/attenddance.service
```

Add the following content:
```ini
[Unit]
Description=AttenDANCE RFID Attendance System
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/attenddance-rfid-system
Environment=FLASK_ENV=production
ExecStart=/home/pi/attenddance-rfid-system/venv/bin/python run.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable attenddance
sudo systemctl start attenddance
```

## Project Structure

```
attenddance-rfid-system/
├── app/                    # Flask application
│   ├── __init__.py        # App factory and initialization
│   ├── models.py          # Database models
│   ├── auth/              # Authentication routes
│   ├── api/               # REST API routes
│   ├── main/              # Main application routes
│   ├── templates/         # HTML templates
│   └── static/            # CSS, JS, images, PWA files
├── rfid/                  # RFID module code
│   ├── __init__.py
│   ├── reader.py          # RFID reading logic
│   └── service.py         # Background RFID service
├── config/                # Configuration files
│   └── config.py          # Application configuration
├── data/                  # Database files (auto-created)
├── requirements.txt       # Python dependencies
├── run.py                # Application entry point
└── README.md
```

## Configuration

The application automatically:
- Creates the SQLite database (`data/attendance.db`)
- Sets up database tables
- Creates a default admin user
- Creates necessary directories

### Environment Variables
You can customize the application using environment variables:

```bash
# Database
DATABASE_URL=sqlite:///data/attendance.db

# Security
SECRET_KEY=your-secret-key
JWT_SECRET_KEY=your-jwt-secret

# RFID Settings
RFID_ENABLED=true
RFID_SPI_DEV=0
RFID_RST_PIN=25

# Server Settings
FLASK_HOST=0.0.0.0
FLASK_PORT=5000
FLASK_ENV=production
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

## Troubleshooting

### RFID Not Working
1. **Check SPI is enabled:** `sudo raspi-config` → Interface Options → SPI → Enable
2. **Verify wiring connections** match the hardware setup above
3. **Check permissions:** Ensure your user is in the `spi` and `gpio` groups:
   ```bash
   sudo usermod -a -G spi,gpio $USER
   ```
4. **Test RFID module:** The application will show RFID status in console output

### Database Issues
- **Reset database:** Delete `data/attendance.db` and restart the application
- **Backup database:** `cp data/attendance.db data/attendance_backup.db`
- **Database permissions:** Ensure the application can write to the `data/` directory

### Service Issues
- **Check status:** `sudo systemctl status attenddance`
- **View logs:** `sudo journalctl -u attenddance -f`
- **Restart service:** `sudo systemctl restart attenddance`

### Permission Issues
If you encounter permission errors with GPIO/SPI:
```bash
sudo usermod -a -G spi,gpio,i2c $USER
sudo reboot
```

## Development

### Running in Development Mode
```bash
export FLASK_ENV=development
python run.py
```

### Testing Without RFID Hardware
The application gracefully handles missing RFID hardware and will run without it for development purposes.

## License

MIT License - See LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Commit your changes (`git commit -m 'Add amazing feature'`)
5. Push to the branch (`git push origin feature/amazing-feature`)
6. Open a Pull Request

## Support

For issues and questions:
- **GitHub Issues**: https://github.com/thomasphillips3/attenddance-rfid-system/issues
- **Documentation**: Check this README and code comments
- **Hardware Issues**: Verify connections and Raspberry Pi configuration 