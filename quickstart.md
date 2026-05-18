# Qima Quickstart

This guide gets the FastAPI backend and Flutter mobile app running locally.
Commands are written for Windows PowerShell from the repository root unless
noted otherwise.

## 1. Prerequisites

- Python 3.11+ available as `python` or `py`
- Flutter SDK available as `flutter`
- Android Studio / Android SDK for phone or emulator testing
- Docker Desktop for local Postgres
- Git

For physical Android testing, enable Developer Options and USB Debugging on the
phone, then accept the USB debugging prompt when it appears.

## 2. Backend Environment

Create and activate a virtual environment:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
```

Create the backend environment file:

```powershell
Copy-Item backend\.env.example backend\.env
```

Edit `backend/.env` and set at least:

```text
DATABASE_URL=postgresql://qima_user:qima_password@127.0.0.1:15432/qima
JWT_SECRET=replace_me_with_a_real_local_secret
```

Set provider keys only for the features you need:

```text
GEMINI_API_KEY=...
GROQ_API_KEY=...
OPENAI_API_KEY=...
```

## 3. Start Postgres

```powershell
docker compose up -d db
```

## 4. Start FastAPI

For local desktop, web, emulator, or USB-forwarded phone testing:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --app-dir backend --host 127.0.0.1 --port 8001
```

Check health in another terminal:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8001/v1/health
```

Expected response:

```json
{"status":"ok"}
```

API docs:

```text
http://127.0.0.1:8001/docs
```

First startup may take longer while local model/OCR dependencies initialize or
download cache files.

## 5. Run Flutter On Android Phone Over USB

This is the recommended phone workflow because it avoids Windows Firewall and
Wi-Fi LAN routing issues.

List devices:

```powershell
cd mobile
flutter devices
adb devices
```

Create the USB reverse tunnel:

```powershell
adb -s <device-id> reverse tcp:8001 tcp:8001
adb -s <device-id> reverse --list
```

Run the app:

```powershell
flutter pub get
flutter run -d <device-id> --dart-define=QIMA_API_BASE_URL=http://127.0.0.1:8001
```

Example:

```powershell
adb -s R5CY82RV2RJ reverse tcp:8001 tcp:8001
flutter run -d R5CY82RV2RJ --dart-define=QIMA_API_BASE_URL=http://127.0.0.1:8001
```

Keep the backend terminal open while using the app.

## 6. Run Flutter On Android Emulator

Start the emulator, then:

```powershell
cd mobile
flutter pub get
flutter run -d <emulator-id> --dart-define=QIMA_API_BASE_URL=http://10.0.2.2:8001
```

Use `10.0.2.2` because Android emulators map that address to the host machine.

## 7. Run Flutter On Chrome

```powershell
cd mobile
flutter pub get
flutter run -d chrome --dart-define=QIMA_API_BASE_URL=http://127.0.0.1:8001
```

## 8. Physical Phone Over Wi-Fi Alternative

USB reverse is preferred. If you need Wi-Fi instead, start FastAPI on all
interfaces:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --app-dir backend --host 0.0.0.0 --port 8001
```

Find the laptop Wi-Fi IPv4 address:

```powershell
Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.IPAddress -notlike '127.*' -and $_.PrefixOrigin -ne 'WellKnown' } |
  Select-Object IPAddress,InterfaceAlias
```

Run Flutter with the laptop LAN IP:

```powershell
flutter run -d <device-id> --dart-define=QIMA_API_BASE_URL=http://<laptop-lan-ip>:8001
```

If the phone cannot open `http://<laptop-lan-ip>:8001/v1/health` in its browser,
Windows Firewall or the network profile is blocking access.

## 9. Run Tests

Backend:

```powershell
$env:PYTHONPATH = "backend"
pytest backend/app/tests
```

Mobile:

```powershell
cd mobile
flutter analyze
flutter test
```

## Troubleshooting

- Phone not listed: reconnect USB, enable USB Debugging, accept the trust prompt,
  then run `adb devices`.
- Phone login times out with USB workflow: run `adb reverse --list` and confirm
  `tcp:8001 tcp:8001` is listed.
- Backend not reachable locally: confirm the backend terminal is still running
  and `http://127.0.0.1:8001/v1/health` returns `{"status":"ok"}`.
- Emulator cannot reach backend: use `http://10.0.2.2:8001`, not
  `http://127.0.0.1:8001`.
- Physical Wi-Fi testing fails: prefer USB reverse, or allow inbound TCP `8001`
  through Windows Firewall and set the Wi-Fi network profile to Private.
