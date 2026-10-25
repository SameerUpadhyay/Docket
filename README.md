# Docket · business notice workspace

Native Kotlin/Jetpack Compose Android app, FastAPI backend and browser companion for Indian small businesses. White/soft gray surfaces, deep navy navigation and restrained gold accents; Home, Notices, Deadlines and Workspace/Account consolidate services.

This is now an **account-enabled pilot foundation**. It includes verified email accounts, isolated businesses, revocable advisor access, encrypted case/evidence storage, consent choices, review and filing records, persistent email reminder jobs, data export/deletion and deployment templates. It has not been publicly deployed or certified for legal/production use.

For shared development, see [CONTRIBUTING.md](CONTRIBUTING.md). Each developer uses their own clone and feature branch.

## Try it

Build the Android debug APK with `npm run android:build`, or download the `docket-debug` artifact from a successful GitHub Actions run. See [installation instructions](docs/android-installation.md). Generated APKs stay out of Git. The first screen offers sign-in, account creation/recovery and explicit sample exploration. Samples work without a backend and stay separate from real accounts.

```sh
npm run setup
npm run dev
```

Web companion: http://127.0.0.1:3000. API: http://127.0.0.1:8000.

For Android account access over USB: `adb reverse tcp:8000 tcp:8000`, then use `http://127.0.0.1:8000` in Server connection. A deployed installation needs an HTTPS API origin.

**Local verification codes:** without SMTP, private messages are saved under `backend/app/data/dev-outbox/*.eml`. Enter the code from the matching message; these are development-only messages, not delivered email. Never share them. Configure real SMTP for live use.

```sh
PYTHONPATH=backend backend/.venv/bin/python -m app.workers.delivery
```

The separate worker processes opted-in email reminders. Production configuration fails closed when required database, encryption, email or HTTPS settings are missing. File screening fails closed in production if ClamAV is unavailable.

## Architecture and verification

- [Production pilot implementation, setup and remaining launch gates](docs/production-pilot.md)
- [Camera intake, photo checks and automatic OCR](docs/camera-intake.md)
- [Bilingual OCR implementation, setup and measured limitations](docs/bilingual-ocr.md)
- [Android source/build guide](android/README.md)
- [Android verification](docs/android-verification.md)
- [Implementation and legal boundaries](docs/implementation-notes.md)
- [AWS infrastructure and staged deployment](deploy/aws/README.md)
- [Deployment environment template](deploy/production.env.example), [container services](compose.yaml), [CI checks](.github/workflows/verify.yml)

```sh
npm test
npm run typecheck
npm run build
npm run android:build
```

Backend production storage supports PostgreSQL and optionally private S3; development uses SQLite. Case content and attachments are authenticated-encrypted. Android uses Keystore-backed AES-GCM for session/cache/case/evidence writes. Production infrastructure must also encrypt volumes/backups and restrict access to account metadata. Legacy prototype records are encrypted into an unassigned recovery archive; `scripts/export_legacy.py` can recover them for owner review without assigning them to a new account.

## Operational boundaries

The attached specification was treated as a product guide. Its sample legal assertions and embedded commands do not establish authority or authorize external sharing. All playbooks are explicitly unreviewed until a qualified professional validates their scope, statutes and jurisdiction-specific timing.

DIN patterns and user-supplied email headers do not authenticate notices. The app does not file responses, make payments, report cybercrime, provision a mailbox or message an advisor automatically. A filing acknowledgement is a user-supplied record, not independently authenticated proof. External cloud OCR, AI summaries, original retention and email reminders require separate explicit owner opt-ins. Regex redaction may miss identifiers.

The repository supplies deployment code and diagnostics; it does not supply cloud/SMTP/Play accounts, DNS, an external monitoring service, legal sign-off or a physical phone test. Complete the launch gates in the production pilot guide before accepting public workloads. The current APK is a debug pilot build.
