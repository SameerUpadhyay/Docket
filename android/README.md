# Native Docket Android pilot

Kotlin + Jetpack Compose, Android 8/API26+, target API36. Standard sans-serif type, white/gray, navy #1B365D and gold #D4AF37. Native UI, ML Kit OCR/QR, Android document pickers, PDF/ZIP export and notifications; no WebView.

## Navigation

- Home: next priority and short case summary.
- Notices: search and consolidated All/Tax/Labour/Legal/Security categories.
- Deadlines: planning timeline.
- Workspace: account/business, storage, mail privacy, reminders and exports.

A case has Overview, Response and Files. Account cases also have one consolidated Review & submission screen with Facts, Review, Filing and History. Account settings group Business, Access and Privacy.

## Accounts

The welcome screen supports sign-in, registration, email verification, resend, password recovery and explicit sample exploration. New real accounts have no fixtures. Verified users can update profiles, switch invited businesses, invite/revoke reviewers/editors, inspect/revoke sessions, export business data, opt into optional processing and delete accounts with a password confirmation.

Backend sessions expire after 12 hours. Android stores opaque tokens and cache data in AES-GCM files using a non-exportable Android Keystore key. Authentication is checked on restoration before loading account cases. Logout removes the account cache and cancels reminders. Remote HTTP, embedded credentials and API-origin paths/query strings are rejected; remote servers must use HTTPS. Access is enforced by the server for every request.

## Build and install

```sh
npm run android:build
adb install -r output/android/docket-debug.apk
adb reverse tcp:8000 tcp:8000
```

Use `http://127.0.0.1:8000` in Server connection for development. `http://10.0.2.2:8000` is also allowed in an emulator. Codes are written to the backend's private dev-outbox when SMTP is not configured. See [production setup](../docs/production-pilot.md).

The build helper discovers JDK17+ and the Android SDK, runs Gradle assemble/tests and copies the debug APK and SHA-256. For Play, provide `DOCKET_API_ORIGIN` for the deployed HTTPS API and private upload-keystore environment settings and run `scripts/android-release.sh`. Release signing, store ownership and final listing/policy configuration must be supplied by the operator. No release private key is bundled.

## Data and review

- Device sample/local workspaces remain separate from authenticated API workspaces. All new local JSON/evidence writes are encrypted. Legacy device JSON/evidence migrates to encrypted files on reading; legacy API cache is discarded at the next successful sign-in and is never assigned to a new account.
- App-private data is excluded from Android backup. Losing the Keystore key or uninstalling removes access to private files. Export required local records first. Account originals/evidence remain governed by the backend retention choices.
- Device OCR uses bundled Latin and Devanagari models for English/Hindi text and QR codes, up to 12 PDF pages, 10MB and 30MP images. Device image data is not sent to an external model. API uploads use the server's OCR/scanner configuration. Compare extraction with originals.
- Facts, response periods and law require human confirmation. A reviewer records findings; credentials are not certified by Docket. Changing a draft invalidates review. Attach the official receipt before recording submission and closing a case. The app performs no filing or payment.
- Local notifications are optional/inexact. Account case facts must be confirmed first. Backend email reminders are separately opted in and delivered by a supervised worker. No SMS/WhatsApp is configured.

## Bilingual OCR

Capture multiple pages in the embedded camera or choose an existing file. Review/retake/reorder photos, then submit one PDF. Photo checks run off the UI thread; English/Hindi recognition is automatic. Pasted text and language selection were removed. See [camera flow and acceptance notes](../docs/camera-intake.md). Read the document to suggest fields before confirming dates and creating a case. Files → Inspect OCR, fields & tables opens source review with candidate locations, bilingual summaries and API table results. See [OCR architecture and current scan limitations](../docs/bilingual-ocr.md). Version **0.4.0-camera-pilot** (code 4).

## Verification limits

See [verification report](../docs/android-verification.md). Native UI/rule/HTTP tests and APK compilation are automated. A real phone/emulator must still validate ML Kit, Keystore, SAF, alarm delivery, process death and battery restrictions. Debug APKs are for pilot testing, not Play release.

Device acceptance: `android/gradlew -p android connectedDebugAndroidTest` runs the dedicated Keystore test on a connected test phone/emulator. Its test APK compiles, but it has not been executed on a device here.
