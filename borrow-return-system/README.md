# Borrow and Return Tool System (Raspberry Pi 5)

A local, offline-ready inventory software for borrowing and returning tools using a USB barcode scanner.

The app is built with:
- Backend: Flask (Python)
- Database: SQLite
- Frontend: HTML + Tailwind CSS + JavaScript
- Runtime target: Raspberry Pi 5 + Chromium

Even though this is a local web app, it is packaged to feel like desktop software with a launcher script and `.desktop` icon.

## Features

- Secure admin login with Flask sessions
- Dashboard with summary cards and recent transactions
- Tool management (add, edit, delete, search, filter)
- Barcode scanner support (keyboard-emulation optimized)
- Borrow module with borrower details and stock validation
- Return module with overdue detection
- Transaction history with filter/search tools
- Reports with chart, print support, and CSV exports
- Offline operation on Raspberry Pi

## Default Login

- Username: `admin`
- Password: `admin123`

Change this in production by updating the admin user in SQLite.

## Project Structure

```
borrow-return-system/
  static/
    css/styles.css
    js/app.js
    js/scanner.js
  templates/
    base.html
    login.html
    dashboard.html
    tools.html
    add_tool.html
    edit_tool.html
    borrow.html
    return.html
    transactions.html
    reports.html
  app.py
  init_db.py
  seed_data.py
  database.db
  requirements.txt
  run.sh
  launch_system.sh
  BorrowReturnSystem.desktop
  README.md
```

## Local Setup (Development)

1. Open terminal in the project folder.
2. Create venv and install requirements:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. Initialize DB and sample data:

```bash
python3 init_db.py
python3 seed_data.py
```

4. Run app:

```bash
python3 app.py
```

5. Open browser:

```text
http://127.0.0.1:5000
```

## Raspberry Pi 5 Deployment (No VS Code Needed)

### 1. Copy Project to Raspberry Pi

Place the project in a path like:

```text
/home/pi/borrow-return-system
```

### 2. Install Required Packages on Pi

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip chromium-browser
```

### 3. Make Scripts Executable

```bash
cd /home/pi/borrow-return-system
chmod +x run.sh
chmod +x launch_system.sh
```

### 4. Launch Like Desktop Software

```bash
./launch_system.sh
```

What happens:
1. Starts Flask app in background (`run.sh`)
2. Waits a few seconds
3. Opens Chromium at `http://127.0.0.1:5000`
4. Uses fullscreen app-style window

## Desktop Icon Setup

1. Update `Exec` and `Path` in `BorrowReturnSystem.desktop` to match your Pi path.
2. Copy launcher file to desktop or applications:

```bash
cp BorrowReturnSystem.desktop /home/pi/Desktop/
chmod +x /home/pi/Desktop/BorrowReturnSystem.desktop
```

Now you can launch by clicking the icon.

## Kiosk Mode Option

Current command in `launch_system.sh`:

```bash
chromium-browser --app=http://127.0.0.1:5000 --start-fullscreen
```

For strict kiosk mode, change to:

```bash
chromium-browser --kiosk http://127.0.0.1:5000
```

## Auto-Start on Boot (Optional)

Use Raspberry Pi desktop autostart file:

```bash
mkdir -p /home/pi/.config/autostart
cp BorrowReturnSystem.desktop /home/pi/.config/autostart/
```

Or add launcher script command in `~/.config/lxsession/LXDE-pi/autostart`:

```text
@/home/pi/borrow-return-system/launch_system.sh
```

## USB Barcode Scanner Notes

- Most USB scanners work as keyboard input.
- Barcode fields auto-focus on Add/Borrow/Return pages.
- Press Enter after scanning if scanner is not configured with suffix Enter.
- Scanner data triggers real-time tool lookup via local API.

## Data Model

Tables:
- `admins`
- `tools`
- `borrowers`
- `transactions`

Schema is created by `init_db.py` and seeded by `seed_data.py`.

## Maintenance

- Back up `database.db` regularly.
- Update dependencies from `requirements.txt` when needed.
- Check logs from launcher run:

```bash
tail -f flask.log
```

## Security Reminder

- Change default admin password immediately for production use.
- Set environment variable for Flask secret key:

```bash
export FLASK_SECRET_KEY="your-strong-secret-key"
```
