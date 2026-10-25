# Install the Docket pilot

`docket-debug.apk` is a native, debug-signed Android application, version **0.4.0-camera-pilot**. It supports Android 8.0/API26 and newer.

1. Copy the APK to your phone and open it using Android's installer. Allow installation from that specific source if Android asks.
2. Launch **Docket**. Choose **Explore sample workspace** to try the fictional cases without a server.
3. For your own business, keep the backend running, choose **Create account**, verify your email and sign in. New accounts start empty.

For a USB-connected test phone:

```sh
adb install -r docket-debug.apk
adb reverse tcp:8000 tcp:8000
```

Use `http://127.0.0.1:8000` in the welcome screen's Server connection. For local development without SMTP, verification/recovery/invitation messages are saved in the backend's private `app/data/dev-outbox` folder. They are not delivered emails. An independent public installation needs the deployed HTTPS backend and real mail delivery.

The app groups Home, Notices, Deadlines and Workspace. Account settings group Business, Access and Privacy. Cases group Overview, Response and Files, with one review/filing/history screen.

Camera: allow access, capture each page, tap thumbnails to review/retake/reorder, then Submit pages. All pages become one document. Obvious blur/dark/blank shots prompt a retake. Language recognition is automatic; there is no paste-text option.

For bilingual intake, capture pages in the app or choose a file, then read the document before confirming its dates and period. Open Files → Inspect OCR, fields & tables to compare source and extracted values. API source previews need original retention enabled before upload. Desktop scan benchmarks still show DIN recognition limitations; compare every critical field with the original. Cloud OCR is implemented but requires provider configuration, model access and separate owner consent.

The APK was built and signature checked; 29 Android tests and 57 backend tests pass. Physical-device installation, Keystore/OCR/file-picker/alarm execution and real AWS services still need acceptance. This is a pilot build, not a Play release. Keep required local records exported before uninstalling; uninstalling loses the app's private device data/Keystore access.

Source and launch gates: `android/README.md`, `docs/production-pilot.md` and `deploy/aws/README.md` in the project.
