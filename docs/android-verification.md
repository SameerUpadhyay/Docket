# Native Android pilot verification

Updated 25 October 2026.

## Artifact

Kotlin/Jetpack Compose, application ID `in.docket.app`, version `0.4.0-camera-pilot` (code 4), min API26 and target API36. Installable debug-signed APK: `output/android/docket-debug.apk`. Wrapper distribution SHA-256 is pinned. Release builds consume an operator-provided HTTPS API origin and private upload-signing settings.

## Completed

- `assembleDebug`, 29 JVM/isolated Android tests and `assembleDebugAndroidTest` compile successfully.
- Twelve deterministic rule tests: fraud/QR screening, PII masking, dates, bounded statutory matching, unknown cases, sample isolation and mail XML.
- Six native UI tests: welcome/account creation/recovery entry; four-tab navigation/filtering/case response/back; quarantine without reply tools; bilingual source inspector with printed table fields; camera/file intake without pasted text or language prompts; camera page review, retake, ordering and single-PDF submission. These render the actual Compose activity in Robolectric API35 native graphics.
- Five OCR tests: Devanagari numerals, candidate dates/periods, uncertainty, language line merging and source order.
- Four camera/automatic-language tests: blur/dark/blank/size screening, EXIF rotation/metadata removal, JPEG PDF assembly/order/limits and detected scripts.
- Two HTTP client tests: authorization/workspace/request headers and rejection of unsafe origins.
- Device-only Keystore test APK compiles. It checks encrypted round trips across instances, tamper rejection and non-exportable keys. **It has not run on a device.**
- Native screenshots: login, registration, Home, Notices, Response, Deadlines, Workspace, Quarantine OCR source/table views, camera intake/permission fallback and zoom review. Screens were visually inspected for readable sans-serif type, spacing, navy/white/gray/gold use and grouped navigation.
- Debug APK signing verified with Android SDK apksigner. SHA-256 is in `output/android/SHA256SUMS.txt`.
- Backend: 57 passing tests, one skipped optional macOS OCR integration test. Tests cover accounts, tenancy, permissions/revocation, recovery, CSRF, encrypted storage/legacy preservation, S3 adapter/deletion outbox, SES adapter, review/receipt/closure, stale drafts, streamed upload limits, reminders, actual bilingual/skewed OCR, decimal table checks, QR quarantine, source retention and cross-business source access.
- Web companion: TypeScript/production build pass; browser sign-in/registration entry, explicit sample mode, Tax filter and deadline navigation were inspected.
- SQLite encrypted backup/verify/restore exercised against a separate temporary database.
- AWS CloudFormation static validation passes for `ap-south-1`. This does not create resources or verify live service integration.

## OCR benchmark

Five fictional documents exercised actual local desktop OCR. Three passed all exact checks; both scan variants retain DIN recognition failures. Reconstructed tax rows and printed-total arithmetic now pass after fixing detection of narrowly separated cell borders. Amount/date/period/GSTIN candidates passed for those scans. All results require source review. See [full OCR report and setup](bilingual-ocr.md) and `output/ocr/benchmark.json`. Live cloud providers, representative real notices and physical Android OCR remain unverified.

## Still requires acceptance

The Android-generated camera PDF was also read by the API as one case with two pages; [camera verification](camera-intake.md) records the exact scope.

No physical phone or complete emulator image was available. Camera preview/shutter/focus/torch, real photo checks and camera responsiveness remain device acceptance items. Keystore runtime, ML Kit OCR, SAF import/export, Android alarm delivery/reboot/battery restrictions, live API usage on a phone and font scaling/talkback remain device acceptance items. APK installation on a phone was not exercised.

Docker/managed PostgreSQL/private S3/ClamAV/live SES were not running here. Provider and container acceptance remain required. The CI PostgreSQL matrix is prepared but has not been executed in GitHub. CloudFormation has not been deployed; the current workspace has no configured AWS profile, and an owned app domain/Route53 zone is still needed.

Legal playbooks and public policies remain drafts pending qualified professional/operator review. This artifact is a pilot debug build, not a Play release or a certification of production readiness.
