# Qima Flutter App Setup

This is the Flutter client for the Qima V1 contract API.

## Prerequisites

- Flutter SDK with Dart `^3.11.5`
- Android Studio or the Android command-line tools
- A JDK available on `JAVA_HOME`
- Chrome, Edge, Windows desktop, or an Android emulator/device
- The Qima FastAPI backend running locally or on a reachable host

Check your Flutter installation:

```powershell
flutter doctor
```

## Install Dependencies

From the repository root:

```powershell
cd mobile
flutter pub get
```

## Backend URL

The app reads the backend URL from the compile-time environment variable `QIMA_API_BASE_URL`.

Default:

```text
http://127.0.0.1:8000
```

Use the default when running on Windows desktop or web against a local backend.

For an Android emulator, use `10.0.2.2` to reach the host machine:

```powershell
flutter run -d emulator-5554 --dart-define=QIMA_API_BASE_URL=http://10.0.2.2:8000
```

For a physical device, use the host machine's LAN IP address:

```powershell
flutter run --dart-define=QIMA_API_BASE_URL=http://192.168.1.10:8000
```

Replace the IP with your machine's actual address.

## Run The App

List available devices:

```powershell
flutter devices
```

Run on Windows desktop:

```powershell
flutter run -d windows
```

Run on Chrome:

```powershell
flutter run -d chrome
```

Run on Android:

```powershell
flutter run -d <device-id> --dart-define=QIMA_API_BASE_URL=http://10.0.2.2:8000
```

## Android Gradle Notes

The Android project uses Gradle `8.13`.

Wrapper config:

```text
mobile/android/gradle/wrapper/gradle-wrapper.properties
```

If Gradle state becomes stale:

```powershell
cd mobile
flutter clean
flutter pub get
cd android
cmd /c gradlew.bat --stop
cmd /c gradlew.bat wrapper --gradle-version 8.13
cd ..
```

## Validate Changes

Run analyzer:

```powershell
flutter analyze
```

Run tests:

```powershell
flutter test
```

Build Android debug APK:

```powershell
cd android
cmd /c gradlew.bat assembleDebug
```

## Current API Compatibility Note

The mobile recipe and chat screens are prepared for the planned price-aware API contract fields:

- `budget`
- `price_preferences`
- `price_context`
- `food_context`
- `active_context_type`

Until the backend schemas are updated, the current strict FastAPI stubs may reject those newer request fields with validation errors. This is expected during the mobile-first integration phase.
