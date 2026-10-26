# Docket

**A fire alarm for legal fires.** An early-warning notice workspace for Indian small businesses.

Built by **Team Artemis** for **Srujana Hackathon 2026 · LS-05: Notice on the Desk**. Formerly LawChakra.

A GST notice, tax letter or legal demand can arrive while an owner is busy running the business. It may sit unread, or be left to someone else, until little time remains to respond. Docket connects that notice to useful action: understand the issue, check its urgency, gather evidence and prepare a response.

Docket is designed to be **set up once and kept ready**. Owners choose which emails to forward; paper notices and portal downloads can be scanned or uploaded. The **native Android app is the main product**, supported by a web companion.

It helps business owners spot what needs attention, accounts staff collect supporting documents, and CAs or lawyers review an organized brief. Professional judgment stays with the qualified advisor.

**Current stage:** a working local prototype with real forwarded-email intake. The backend must remain running; always-on hosting and live outgoing alerts are still to be configured. The Android pilot build is `0.5.3-email-fixes`. Extracted facts, authenticity and legal deadlines require human confirmation.

**Try it:** [Download the Android APK](https://github.com/SameerUpadhyay/Docket/releases/latest/download/docket-debug.apk) · [GitHub Releases](https://github.com/SameerUpadhyay/Docket/releases) · [Installation and backend connection](docs/android-installation.md). Explore fictional sample cases offline; business accounts and incoming mail require the backend.

## From a notice to a next step

1. **Set up:** connect a receiving address and review a selective Gmail rule. Docket does not request whole-inbox access.
2. **Receive:** matching forwarded mail enters the workspace while the service runs; add paper notices or portal downloads by camera or file upload.
3. **Understand:** review English/Hindi text, the apparent sender, law, amount, printed response period and warning signs. Missing facts stay unconfirmed.
4. **Prepare:** check the original, confirm service and response-period facts, plan the deadline, collect evidence and prepare a reply structure for professional review.
5. **Keep track:** maintain evidence, drafts and review history; export a brief and record the filing acknowledgement. Suspicious messages receive a separate safety review; warnings are not verdicts.

Each business has a separate workspace with owner/editor/reviewer access. Case content and evidence are encrypted, with export/deletion controls and separate choices for original retention, cloud OCR, AI summaries and email reminders.

## Project layout

| Directory | Purpose |
| --- | --- |
| `android/` | Native Kotlin + Jetpack Compose app; Android 8/API 26 or newer |
| `backend/` | FastAPI API, accounts, local OCR, email intake and background workers |
| `frontend/` | Next.js + React web companion |
| `scripts/` | Development, build, OCR and infrastructure helpers |
| `docs/` | Setup guides, implementation details and verification limits |
| `deploy/`, `compose.yaml` | Production configuration and deployment templates |

Development uses SQLite; production supports PostgreSQL and optional private S3 storage. Android protects local data with Keystore-backed encryption. Server case content and attachments are encrypted; infrastructure must also protect account metadata, disks and backups.

## Start locally

Install Git, Node.js **24** (the CI version), and Python **3.12+**. For document OCR, install Tesseract with English/Hindi support and follow the [OCR setup guide](docs/bilingual-ocr.md). The setup scripts install application and test packages; they do not provision hosting or download every system tool.

```sh
git clone https://github.com/SameerUpadhyay/Docket.git
cd Docket
```

**Windows PowerShell**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1
```

Pass `-Python "C:\path\to\python.exe"` to `setup.ps1` if Python is outside PATH. The launcher loads supported local tools from `.tools/`, writes backend logs there, and stops the API when the web process exits.

**macOS / Linux**

```sh
npm run setup
npm run dev
```

Open **http://127.0.0.1:3000**. The backend runs at **http://127.0.0.1:8000**, with development API documentation at `/docs`. Use **Explore sample workspace**, or create your own account.

**Email verification:** codes are random, expiring and single-use. Without SMTP/SES configuration, development messages are saved privately in `backend/app/data/dev-outbox/*.eml`; they are not delivered to your inbox. There is no fixed signup code. Supply real mail settings through the server environment for delivered verification and recovery emails.

## Build and connect Android

Android builds need **JDK 17**, SDK platform **36**, and compatible Android build tools. Open `android/` in Android Studio, or run:

```powershell
# Windows: builds the APK, runs native tests and compiles device tests
npm run android:build:windows
```

On macOS/Linux, use `npm run android:build`. The generated APK is `output/android/docket-debug.apk`; successful GitHub Actions Android jobs also publish a `docket-debug` artifact. A verified pilot APK and its checksum are included in [`downloads/android/`](downloads/android/). Build outputs and signing keys stay private.

The APK does **not** contain the Python backend. For account access on a USB-authorized phone, keep the backend running and run:

```sh
adb reverse tcp:8000 tcp:8000
```

Then set **Server connection** to `http://127.0.0.1:8000`. Without that bridge, `127.0.0.1` refers to the phone itself. Remote installations need a deployed HTTPS API. See [Android installation](docs/android-installation.md) and the [Android build guide](android/README.md).

## Set up selective email intake

1. Configure a dedicated receiving provider: **AgentMail** with an inbox-scoped read-only key, **Postmark**, or a trusted **HMAC-signing adapter**.
2. Open **Account → Email**, enable receiving, and complete Gmail's forwarding confirmation for that destination.
3. Inspect and import the generated Gmail filter. Keep forwarding for all messages disabled, and review the included demonstration senders before using the rule with real mail.
4. Review incoming cases and confirm their facts before planning deadlines or preparing a response.

A preview address ending in `inbound.example.invalid` cannot receive Internet email. A forwarding destination must differ from your source Gmail account; dot/plus aliases do not create a separate mailbox. Each dedicated AgentMail inbox belongs to one workspace.

Provider credentials stay on the backend. For Windows development, `scripts/dev.ps1` loads allowlisted receiving settings from ignored `.secrets/inbound.env`. Other environments should supply those variables directly. Never put a provider key into the web app, APK or tracked configuration. See the [complete email setup and privacy guide](docs/email-ingestion.md).

Development runs an inline intake worker. Production needs continuously running email intake and reminder workers, configured receiving/sending services, and the database and malware scanner. Receiving and sending email are separate integrations. Keep the server running for incoming mail; an installed APK alone does not process it.

## Checks and collaboration

```sh
npm test
npm run typecheck
npm run build
npm run android:build
```

For backend tests on Windows:

```powershell
. ./scripts/tools-env.ps1
& backend/.venv/Scripts/python.exe -X utf8 -m pytest -q backend/tests
```

Stop the development server before a frontend production build, then restart it. Native tests do not replace testing the camera, OCR, notifications and account flow on real devices. [CI](.github/workflows/verify.yml) checks the backend with SQLite/PostgreSQL, web build, Android build/tests and infrastructure templates.

Use your own clone and feature branch, then open a pull request into `main`; see [CONTRIBUTING.md](CONTRIBUTING.md). Commit source, locked dependencies and fictional fixtures. Keep `.env` files, `.secrets/`, local databases, notices, outbox messages, credentials, runtimes and generated artifacts private.

## Deployment and limits

Start with the [production pilot guide](docs/production-pilot.md), [environment template](deploy/production.env.example), [Compose services](compose.yaml), and [AWS deployment guide](deploy/aws/README.md). Templates do not create a live service by themselves. Production checks require explicit database, encryption, email and HTTPS configuration; file processing fails closed when required malware screening is unavailable.

OCR, redaction and signature checks have limits. A valid mail signature does not prove a legal notice is genuine, regex masking can miss identifiers, and playbooks require qualified professional validation. Docket does not automatically file responses, make payments, contact advisors or authenticate filing acknowledgements. External processing and reminders require their own owner opt-ins.

Further detail: [bilingual OCR](docs/bilingual-ocr.md) · [camera intake](docs/camera-intake.md) · [Android verification](docs/android-verification.md) · [implementation boundaries](docs/implementation-notes.md).
