# Install Docket on Android

[Download docket-debug.apk](https://github.com/SameerUpadhyay/Docket/raw/refs/heads/main/downloads/android/docket-debug.apk) — **0.5.3-email-fixes**, version code **8**, Android **8.0/API 26 or newer**, about **83 MiB**. The APK is included in this repository under `downloads/android/`, with its SHA-256 in `SHA256SUMS.txt`. You need repository access while the project is private.

1. Download the APK on your phone and open it with Android's installer. Allow installation from that specific source if prompted.
2. Launch **Docket** and choose **Explore sample workspace** to try fictional notices offline.
3. For your own business account and forwarded mail, connect to a running Docket backend, then sign in or create an account. The APK does not include a hosted server or mail-service credentials.

## Connect to the backend

For a USB-connected, debugging-authorized phone, keep the backend running on your computer and run:

```sh
adb install -r downloads/android/docket-debug.apk
adb reverse tcp:8000 tcp:8000
```

Use `http://127.0.0.1:8000` under **Server connection** on the welcome screen. Without the ADB bridge, `127.0.0.1` refers to the phone itself. Remote use requires a deployed HTTPS backend. Repeat port forwarding after reconnecting the phone.

For development without SMTP/SES, verification, recovery and invitation messages are saved in the backend's private `app/data/dev-outbox` folder. They are not delivered email. Signup uses random, expiring codes; there is no hardcoded verification code. Real email delivery requires server configuration. Forwarded notices additionally require the receiving setup in [Account → Email](email-ingestion.md).

## Updates and integrity

The pilot APK is debug signed. Updating over an APK signed by the same key normally preserves app data. Android may reject a build signed by a different key or with a lower version code. If the experimental 0.5.4 build is installed, an authorized ADB connection can attempt the restored build with `adb install -r -d downloads/android/docket-debug.apk`. Export device-only records before considering an uninstall: uninstalling removes private device data and Keystore access.

Check the downloaded file against [SHA256SUMS.txt](../downloads/android/SHA256SUMS.txt). For example, from `downloads/android/` on macOS/Linux, run `sha256sum --check SHA256SUMS.txt`; in PowerShell, use `Get-FileHash ./docket-debug.apk -Algorithm SHA256`. CI checks the committed APK's checksum, signature and package/version before building and testing the Android source. The separately generated CI artifact can use a different runner debug key.

## Document intake and verification limits

Capture multiple pages or choose a file, review the extraction, then confirm dates and response periods against the original. **Files → Inspect OCR, fields & tables** shows the analysis; API source previews require original retention enabled before upload. English/Hindi OCR and QR screening can miss information and need human review.

The app groups Home, Notices, Deadlines, Workspace and Account, with case responses, evidence, review and filing records. It does not file legal responses or make payments automatically. Physical-device camera, OCR, Keystore, file-picker and notification behavior still require acceptance testing. This is a pilot debug build, not a Play Store release.

See the [Android build guide](../android/README.md), [production setup](production-pilot.md) and [email intake guide](email-ingestion.md).
