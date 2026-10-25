> Historical prototype report (24 October 2026). Current account-enabled pilot verification is in [android-verification.md](android-verification.md) and [production-pilot.md](production-pilot.md).

# Verification

Completed locally on 24 October 2026.

- Backend: 20 unit/API regression tests pass. A separate optional macOS integration test passes for an image containing only a synthetic UPI QR code, including proof that no external AI call occurs.
- Frontend: TypeScript check and optimized Next.js production build pass.
- Browser: ledger navigation, Hindi summary, evidence collection with a persisted state change, editable and saved draft, PDF download, quarantine lockout and pasted-notice analysis checked.
- Responsive: 390px viewport checked; document width equals viewport width, with working mobile ledger and intake controls.
- Image reader: synthetic printed notice extracted locally; synthetic UPI QR decoded locally. Test files contain fictional values only.
- PDF: reply and complete professional brief rendered with Poppler and inspected. The sample professional brief fits on one A4 page with letterhead, section labels and page footer.

The test suite uses a temporary database. Browser QA used a synthetic uploaded notice; that QA record was removed afterward, and the five-case demo was restored.

Not exercised: a live Gemini API call, actual receiving mail gateway, authority registry checks, email/SMS/WhatsApp delivery or legal filing. The UI does not represent these services as active.
