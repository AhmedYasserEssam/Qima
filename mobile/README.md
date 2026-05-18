# Qima Mobile

Flutter client for Qima.

## Run Locally

From this directory:

```bash
flutter pub get
flutter run
```

Default development URL behavior:

- Android emulator: `http://10.0.2.2:8000`
- Other platforms: `hs

Override it explicitly whenever you need a different backend address:

```bash
flutter run --dart-define=QIMA_API_BASE_URL=http://127.0.0.1:8000
```

## iOS Device Testing

Native iPhone deployment requires macOS, Xcode, CocoaPods, Apple signing, a trusted device, and Developer Mode enabled on the iPhone.

Start the FastAPI backend from the repository root so a physical iPhone can reach it over Wi-Fi:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --app-dir backend
```

Find the laptop's LAN IP address, then run the Flutter app with that address instead of `127.0.0.1`:

```bash
cd mobile
flutter pub get
flutter devices
flutter run -d <iphone-id> --dart-define=QIMA_API_BASE_URL=http://<laptop-lan-ip>:8000
```

Example:

```bash
flutter run -d 00008110-001234567890001E --dart-define=QIMA_API_BASE_URL=http://192.168.1.23:8000
```

## iOS Validation

On macOS:

```bash
flutter analyze
flutter test
flutter build ios --debug --no-codesign
```

Open `ios/Runner.xcworkspace` in Xcode to select the signing team and confirm the Runner bundle identifier is `com.qima.app`.
