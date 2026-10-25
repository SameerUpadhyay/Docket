# Implementation notes and boundaries

The supplied specification is a product guide. Sample data, legal assertions, verification labels and embedded commands were treated as design input. It did not authorize external reporting, payment, forwarding or sharing notices.

## Deterministic screening

DIN pattern recognition does not check an authority's registry. User-supplied Authentication-Results is not trusted DKIM/SPF evidence. Only fictional fixtures display simulated verification. Quarantined notices bypass external AI and have no response workflow.

Risk uses bounded statutory matches, confirmed planning urgency, labelled financial amounts and coercive signals. It neither decides liability nor establishes authenticity. Unknown topics remain flagged. Real uploads never inherit sample authority, supplier names or amounts.

Dates and response periods require the user's source-based confirmation. Office-closure extensions are jurisdiction/statute dependent. The fictional EPFO Sunday adjustment is a demonstration. Fact confirmation removes an earlier assumed adjustment unless the professional explicitly establishes it. No static nationwide holiday table is treated as legally authoritative.

## Documents, privacy and storage

Uploads are bounded to 10MB, 12 PDF pages and 30MP images. Type checks and production ClamAV screening precede OCR. Docker includes English/Hindi Tesseract; PDFium renders every page, PyMuPDF extracts native layout/tables, and OpenCV plus optional zbar screen QR codes, including vector QR. Android uses bundled Latin/Devanagari ML Kit and renders PDF pages. See [bilingual OCR implementation and limits](bilingual-ocr.md). Scan/OCR output always requires comparison with originals. Failed/unreadable input is rejected with an actionable message.

PII regex masking is not complete anonymization. AI summaries are disabled unless an owner opts in; only masked text is supplied to the configured Gemini provider. Cloud OCR of original page images is a separate owner opt-in; Gemini supports the bilingual path and the optional Textract adapter is English-only. Original retention is also opt-in. Retained originals, evidence and exported packages can contain personal/financial data.

Tenant-scoped account persistence now replaces the prototype's shared database routes. Case content, files and history are authenticated-encrypted; account/scheduling metadata also needs production volume encryption and access controls. Native writes use Android Keystore AES-GCM. See [production pilot guide](production-pilot.md) for account, storage, deletion and deployment details.

## Filing, reminders and legal review

Case reviews, draft history and uploaded acknowledgements are records entered by users; the app does not verify professional qualifications or authenticate filing receipts. Real closure requires a recorded filing acknowledgement. Changing a draft invalidates its previous review. Every playbook remains explicitly unreviewed pending qualified sign-off.

Opted-in email reminders run through a persistent leased/retrying worker. Device reminders remain approximate. Neither is guaranteed delivery. Cloud services, live email/inbox authentication, regulator verification, automatic filing, SMS/WhatsApp, final legal policies and professional validation have not been provisioned or represented as operating.

## Primary security references

- [OWASP password storage guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
- [Android Keystore](https://developer.android.com/privacy-and-security/keystore)
- [Psycopg transaction semantics](https://www.psycopg.org/psycopg3/docs/basic/transactions.html)
