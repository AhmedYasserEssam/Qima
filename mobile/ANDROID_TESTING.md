# Android Testing Guide

This guide covers testing the Qima Flutter app on an Android emulator or a physical Android phone.

## Prerequisites

- Flutter SDK installed and available in your terminal.
- Android Studio installed with the Android SDK and at least one emulator, or a physical Android phone with USB debugging enabled.
- FastAPI backend dependencies installed.
- Backend database running and `backend/.env` configured with `DATABASE_URL`.

If you are testing backend calls over local HTTP, the Android app must allow network access. Verify `mobile/android/app/src/main/AndroidManifest.xml` includes:

```xml
<uses-permission android:name="android.permission.INTERNET" />
```

For a local non-HTTPS backend, the `<application>` tag must also allow cleartext traffic during development:

```xml
<application
    android:usesCleartextTraffic="true"
    ...>
```

## Start the Backend

From the repository root:

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --app-dir backend
```

Keep this terminal running while testing the mobile app.

## Test on an Android Emulator

Start an emulator from Android Studio, then run:

```powershell
cd mobile
flutter pub get
flutter devices
flutter run -d <emulator-id> --dart-define=QIMA_API_BASE_URL=http://10.0.2.2:8000
```

Use `10.0.2.2` because Android emulators map that address to the host laptop's `localhost`.

Example:

```powershell
flutter run -d emulator-5554 --dart-define=QIMA_API_BASE_URL=http://10.0.2.2:8000
```

## Test on a Physical Android Phone

On the phone:

1. Enable Developer Options.
2. Enable USB Debugging.
3. Connect the phone to the laptop by USB.
4. Accept the USB debugging prompt on the phone.
5. Make sure the phone and laptop are on the same Wi-Fi network.

Find the laptop's LAN IP address:

```powershell
ipconfig
```

Use the IPv4 address for your active Wi-Fi or Ethernet adapter, for example `192.168.1.23`.

Then run:

```powershell
cd mobile
flutter pub get
flutter devices
flutter run -d <android-device-id> --dart-define=QIMA_API_BASE_URL=http://<laptop-lan-ip>:8000
```

Example:

```powershell
flutter run -d R58N123ABC --dart-define=QIMA_API_BASE_URL=http://192.168.1.23:8000
```

## Smoke Test Checklist

- App installs and opens.
- Signup or login works.
- Debug or health screen reaches the FastAPI backend.
- Manual barcode lookup works with `5449000000996`.
- Barcode scanner opens and prompts for camera permission.
- Food image capture/upload opens the camera or picker.
- Auth state persists after closing and reopening the app.

## Troubleshooting

- `flutter devices` does not show the phone: confirm USB debugging is enabled, reconnect the USB cable, and accept the trust prompt.
- Backend is unreachable on emulator: use `http://10.0.2.2:8000`, not `127.0.0.1`.
- Backend is unreachable on physical phone: use the laptop LAN IP, confirm both devices are on the same network, and allow port `8000` through the laptop firewall.
- HTTP requests fail immediately: verify `INTERNET` permission and development cleartext traffic are enabled in `AndroidManifest.xml`.
- Camera scanner does not open: verify camera permission is present and grant camera access when Android prompts.
