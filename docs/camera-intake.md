# Camera intake and automatic bilingual OCR

Native Android version **0.4.0-camera-pilot**, 25 October 2026.

## Flow

Add notice offers **Capture pages** and **Choose file**. Pasted text and the language picker have been removed from Android and browser intake. Existing file uploads remain available.

The native camera uses CameraX inside Docket. Allow camera access, frame the complete page, tap to focus and capture. Keep taking pictures for a document of up to 12 pages. Tap a page thumbnail to review it with zoom, retake it, remove it or move it earlier/later. A rejected retake keeps the previous accepted photo and all other pages.

**Submit pages** assembles the JPEGs in the chosen order into one PDF, then reads it through the existing intake flow. In account mode this uploads one PDF to the API; in the local workspace OCR stays on the device. This does not file a legal response. Confirm the suggested issue date, service date and applicable period before creating the case. Camera draft pages remain available while confirming the notice, so you can reopen Capture pages and replace a page without photographing the others again.

The browser companion keeps file upload and automatic language handling; the embedded multipage CameraX capture is an Android feature.

## Fast photo checks

The app checks a small, downsampled image off the main thread for severe blur/low detail, darkness, blank/washed-out images and insufficient resolution. Rejected shots prompt **Retake this page** immediately after checking and are not added to the document. No network request or OCR model runs for every camera frame or shot. Thumbnails are cached, only one capture is processed at a time, and PDF assembly streams existing compressed JPEGs rather than decoding all pages at once. The complete document remains subject to the 10 MB upload limit; oversized assembly keeps the pages for correction rather than silently discarding or degrading them.

These checks are conservative heuristics, not a guarantee of legibility. Noise, glare over one region, small text, obstructions and unfamiliar layouts can pass a quick check. Use zoom review before submitting; OCR still flags uncertain characters afterward. Phone latency, thresholds and camera behavior need physical-device evaluation.

## Automatic recognition

Clients request `ocr_language=auto`. The server uses native PDF text/layout when appropriate and a bilingual English/Hindi recognizer for scanned pages, or consented Gemini transcription when configured. Android uses bundled Latin and Devanagari recognition. Both scripts are available in the same pass so mixed-language pages are retained. Detected scripts are reported after recognition; the app never guesses a single language from a filename or asks the user to choose. Existing explicit-language API callers remain compatible. Auto mode uses the local bilingual path rather than the English-only Textract adapter.

## Storage

Camera permission is requested only from the capture screen. No gallery/storage/location permission is added. Captures are normalized for EXIF rotation/reflection, resized with a bounded bitmap and saved as JPEG without original metadata. Photos, thumbnails and pending PDFs use private app cache. Cancelling the intake, changing source, completing the case or discarding the camera draft clears the relevant temporary files. Abandoned files older than 24 hours are pruned on a later app launch. Cache can also be removed by Android.

Normal activity configuration changes retain the camera draft through its ViewModel. Recovery after process death is not implemented; an interrupted draft may need recapturing. A completed local camera case keeps its source PDF encrypted with Android Keystore AES-GCM for the inspector; a complete local ZIP export includes that original. Account original retention remains controlled by the separate workspace preference. Temporary capture does not enable cloud OCR or original retention automatically.

## Verification

- 29 Android tests pass, including native intake/permission fallback, zoom review, bad-retake preservation, replacement, ordering, one-PDF submission, cancellation cleanup, blur/dark/blank/size checks, EXIF/GPS handling and document limits.
- 57 backend tests pass, with one optional macOS integration test skipped. New checks cover automatic English/Hindi/mixed recognition and the default preview route.
- The actual Android-generated fictional two-page PDF parses strictly, retains two JPEG images in the chosen order and passes local OCR. The standalone in-process API check verifies that preview creates no case and one document upload creates one case with two pages. Run `backend/.venv/bin/python scripts/verify_camera_fixture.py` after `npm run android:build`; results are in `output/ocr/camera-capture-verification.json`.
- Web TypeScript/production build passes. The updated native intake, camera permission fallback and page-review screens were rendered and inspected in Robolectric.

No physical camera or complete emulator is available here. CameraX preview, runtime permission grant/revocation, actual shutter/focus/torch, rotation, background/restore, low-memory behavior and capture responsiveness still require phone acceptance. Live cloud OCR remains untested. This is a debug pilot APK.
