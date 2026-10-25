# English + Hindi OCR pilot

Implemented 25 October 2026 from `codex_bilingual_ocr_triage_implementation_specification.md`, integrated with the existing native Android, account, privacy and case workflows. The attached document was a product guide; its example defaults and embedded instructions were not treated as authority to share originals or invent legal facts.

## What the app does

Capture pages in the Android app or choose a document, then **Read document & suggest fields**. English/Hindi recognition is automatic; there is no pasted-text or language-choice prompt. See [camera intake](camera-intake.md). This preview creates no case or deadline. Compare the suggestions with the original, confirm the service date and applicable response period, and create the case. Files → **Inspect OCR, fields & tables** shows the source, field locations, English/Hindi explanation, reconstructed amounts, arithmetic status, warnings and redacted transcript. The browser companion has a split source/fields inspector. The mobile inspector stacks these sections for a small screen.

Server previews and final case creation each perform extraction; there is no server result cache. With cloud processing enabled, reading a preview and then creating a case can make two provider requests per scanned page. Native local intake caches its reading in memory for the same content/language. Source inspection for account cases requires original retention to have been enabled before case upload; otherwise the app explains why an original is unavailable. Local file-upload cases reference the user-selected document URI, whose permission/file can later become unavailable. Completed local camera cases keep their combined original PDF encrypted for source review.

## Extraction stages

1. **Bounded ingestion:** authenticated, tenant-scoped uploads; type/decode and production malware checks; 10 MB/file, 12 PDF pages, 30 MP/image. PDFium renders all accepted pages at 300 DPI subject to the pixel budget. PDF text and measured native lines/tables come from PyMuPDF; copy-text encoding disagreements are flagged and damaged Hindi glyph lines may be recovered from independent visual OCR. No five-page shortcut or silent unreadable-page omission is used.
2. **Image and QR screening:** EXIF correction, conservative perspective correction, crop-free deskew and LAB CLAHE. Transformation matrices map detections back to original coordinates. OpenCV screens raw/enhanced pages, including rendered vector QR codes, before cloud extraction. Optional zbar adds a decoder. Recognized scam signals bypass cloud processing and quarantine the case. QR screening is not a guarantee of authenticity or complete malicious-code detection.
3. **Text and grids:** local Tesseract `eng+hin` with locked best models; optional consented Gemini page transcription; optional English-only AWS Textract. Ruled table regions can receive border-only suppression and a bounded second recognition pass, including uncertain numeric cells. Missing cells remain unknown. Stamp suppression is available as an experimental candidate helper, and does not replace primary recognition because colored ink can be material evidence. Borderless/merged/multipage tables and handwritten/obscured text still require acceptance testing.
4. **Independent cross-checks:** normalize Devanagari digits; extract candidate DIN/GSTIN/PAN/sections/dates; compare independently printed totals with component amounts using Decimal and a one-paise tolerance. Missing tables/cells give **not verified**, and inconsistent totals give a discrepancy. Arithmetic agreement does not prove the recognition is correct. Reference rereads are actual image recognition, never a guessed Z/2 or O/0 substitution.
5. **Review and integration:** strict typed payloads, nullable missing facts, deterministic notice family/risk rules and conservative bilingual summaries. Model transcription cannot set a statutory deadline, decide liability, certify authenticity or supply legal authority. Unknown/conflicting dates and periods require source confirmation. Highlights use measured native/local geometry or explicitly labeled model estimates; invalid model boxes are rejected. No fake boxes, invented issuer, date, amount or default 15-day response period is inserted. The legacy payload field `image_quality_score` holds the raw Laplacian sharpness statistic, not a calibrated 0–100 score or accuracy percentage.

The summaries describe the detected family, labeled amount and period. They are conservative templates, not a full legal interpretation or fluent translation of every allegation. Existing optional AI summaries remain separately consented. The draft is a professional-review skeleton. Notice-family rules and legal playbooks require professional validation.

## Runtime and privacy

| Path | Runtime | Original leaves device/server? |
| --- | --- | --- |
| Native local workspace | Bundled ML Kit Latin + Devanagari recognizers and QR scanner | No external OCR provider |
| API with local OCR | Tesseract English/Hindi + PDF/layout/OpenCV pipeline | Uploaded to the configured app server; no external OCR provider |
| API with cloud OCR | Configured Gemini model for weak/scanned pages; local fallback on provider failure | Original page images can reach Google after workspace-owner opt-in |
| Optional English cloud path | AWS Textract DetectDocumentText | Original pages can reach AWS after owner opt-in; Hindi uses local processing |

`cloud_ocr`, `external_ai` (masked summaries), `retain_original` and `email_reminders` are separate owner choices, all off by default. Regex redaction is not complete anonymization. Provider OCR sees original page images when enabled. Protected source-image routes enforce membership, require retained originals and send `Cache-Control: no-store`. OCR-first previews do not persist originals/cases. API responses/persisted analysis reuse intake redaction tokens across nested fields/transcripts.

Android's bundled models work without a model download after installation. The structured financial-table pipeline runs on the API; local-only Android provides bilingual reading, candidate fields and source review, rather than equivalent server table analysis.

## Setup

Install backend dependencies and a supported Tesseract executable. Both English and Hindi trained data are required. This workspace has an isolated Tesseract 5.5.3 under ignored `.tools/ocr`; other machines must install their own runtime. Docker installs Tesseract and both models. CI and Docker fetch official `tessdata_best` files and verify the committed SHA-256 manifest.

```sh
PYTHONPATH=backend backend/.venv/bin/python -m app.ocr.model_setup --destination .tools/tessdata
PYTHONPATH=backend backend/.venv/bin/pytest -q backend/tests
backend/.venv/bin/python scripts/benchmark_ocr.py
npm run android:build
```

The model downloader downloads trained data only, never documents. Set `TESSERACT_CMD` and `TESSDATA_PREFIX` if the executable/model directory is elsewhere. `OCR_PROVIDER=local` is the default. Clients now request `ocr_language=auto`: both scripts are recognized together, and detected languages are reported from the result. For cloud use, set `OCR_PROVIDER=gemini`, supply `GEMINI_API_KEY` through the hosting secret manager, and select `GEMINI_OCR_MODEL`. The guide's `gemini-2.5-flash` default is configurable. Google currently restricts 2.5 access for new projects; confirm model entitlement and select/evaluate an available image + structured-output model before enabling cloud OCR. Do not assume the API key alone enables original sharing. The owner must also save the Cloud OCR choice.

AWS infrastructure supports an optional `GeminiSecretArn`; it continues to use RDS/S3/SES for the selected hosting setup. Gemini is an additional Google processor, not an AWS service. The AWS resources have not been deployed. `OCR_PROVIDER=textract` is available for explicitly English requests only.

Work is bounded to two page workers, one simultaneous document by default (`OCR_MAX_CONCURRENT_DOCS`), a 75-second extraction budget and bounded subprocess/provider timeouts. Saturation rejects new work with an actionable error. This is synchronous request processing, not a camera livestream or a real-time SLA. A timed-out native operation can continue until its own timeout. Capacity, memory and queue behavior need load testing before scaling.

PyMuPDF is a runtime dependency with AGPL/commercial licensing. Resolve the appropriate license or replace this component before a proprietary launch. The test Hindi font includes its OFL license. See the provider/library references below.

## Verification and current limits

The reproducible report is `output/ocr/benchmark.json`; it uses five **fictional** documents and actual desktop local OCR, without any cloud call. Digital bilingual GST, cheque Section 138 and rendered vector-QR scam checks pass. Both scan variants recover the labeled INR 160,000 amount, issue date, 15-day candidate and GSTIN, and now reconstruct both tax rows with agreeing printed totals, but **do not pass exact DIN checks**. These are retained as benchmark failures, not hidden or repaired by guessing. The latest desktop run took 2.8–4.9 seconds per synthetic document (median 4.3 seconds); this is not an SLA. The app marks uncertain references and unverified tables for source review.

Automated tests cover actual bilingual/skewed extraction, source geometry, independent arithmetic and missing cells, QR cloud bypass, unknown/conflicting facts, nested masking, unreadable later-page rejection, authentication, source retention and cross-business isolation. Native Compose tests render the actual inspector. Full counts and artifact details are in `android-verification.md`.

Live Gemini/Textract, physical Android ML Kit and a representative permissioned/redacted real-notice corpus have **not** been tested. No 99% accuracy or real-time performance claim is made. Before relying on this for real notices, evaluate exact critical-field accuracy (IDs, dates, amounts), Hindi character errors, table cell/row accuracy, false quarantine rates, document completeness and p50/p95 latency on digital, camera, blur, stamps, shadows, rotation, mixed/borderless tables and multipage notices. Keep held-out examples and professional ground truth; failures must remain reviewable. Provider model changes require re-evaluation.

## Primary references

- [ML Kit Android bundled Latin/Devanagari recognition](https://developers.google.com/ml-kit/vision/text-recognition/v2/android)
- [Gemini 2.5 Flash model capabilities and access notice](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash)
- [AWS Textract supported languages](https://aws.amazon.com/textract/faqs/)
- [PyMuPDF license options](https://pymupdf.readthedocs.io/en/latest/about.html)
