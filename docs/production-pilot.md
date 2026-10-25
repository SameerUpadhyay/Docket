# Docket account-enabled pilot

Implemented on 25 October 2026. This is a runnable pilot foundation. It has not been deployed, independently security audited, professionally approved for legal accuracy, or tested on a physical Android phone.

## What now works

- Verified email registration, 12+ character passwords with scrypt (N=131072, r=8, p=1), expiring verification/reset codes with bounded guesses, generic account recovery messages, rate limits and 12-hour revocable opaque sessions. Password reset signs out every device. Session tokens are hashed on the server. Browser sessions use HttpOnly SameSite cookies; native clients use bearer authentication.
- Owner-controlled business workspaces, editor/reviewer roles, expiring email invitations tied to the recipient's verified email, business switching and immediate access revocation. Every case, attachment, export and history query is scoped to authenticated business membership. New accounts never receive sample cases. `DOCKET_DEMO_MODE=1` is an explicit test-only bypass and is ignored in production.
- Case content, evidence and history encrypted with Fernet authenticated encryption. PostgreSQL is the production database; SQLite is the development database. Identity, access and scheduling metadata require encrypted infrastructure disks and restricted database privileges as well. Optional private S3 stores already-encrypted attachments; the API mediates access. Replacement/deletion queues object removal for the worker. Configure bucket lifecycle cleanup for orphaned objects from a crash during upload.
- Native account/cache files and local case/evidence writes use AES-GCM and a non-exportable Android Keystore key. Logout removes the account cache and cancels local reminders. Existing legacy server data is not assigned to any new user. Legacy local JSON and referenced evidence migrate to encrypted files on reading; the old API cache is never assigned to a new account and is discarded at sign-in.
- Original-document SHA-256, optional original retention (off by default), type inspection, 10 MB/file, 12-page PDF and 30 MP image limits, malware screening through private ClamAV (fails closed in production). Docker includes local English/Hindi Tesseract, PDFium rendering, PyMuPDF native layout/tables and OpenCV QR decoding; bundled Latin/Devanagari ML Kit remains local on Android. See [OCR verification and remaining accuracy limits](bilingual-ocr.md). OCR and scan coverage must be checked against originals.
- Human fact confirmation, explicit response periods, professional review decisions and notes, encrypted case history and previous draft versions, stale-draft conflict checks, filing receipt attachments, acknowledgement reference/date/channel and closure guards. The app records an external filing; it never files a response or independently validates a receipt.
- Persistent T−7/T−3/T−1 email jobs at 09:00 IST after fact confirmation and owner opt-in. Separate delivery worker, atomic claims, leases, retries/backoff, expiry, failure status and heartbeat. SMTP is at-least-once; a crash after sending may produce a duplicate. Closed/deleted cases stop pending jobs. Mobile reminders are optional and approximate.
- Privacy/terms draft pages, versioned registration consent, separate explicit opt-ins for cloud OCR of original images, future original retention, external AI summaries and email reminders; case deletion, account/business data export and password-confirmed account deletion. Account deletion removes owned businesses and revokes sessions; it does not delete another owner's business records. The public web companion provides a deletion route without requiring the Android app.
- Production configuration checks, non-root Docker images, HTTPS gateway, private database/scanner network, PostgreSQL migrations with advisory locking, redacted request diagnostics, readiness endpoint, delivery health, backup helper, release-signing configuration and CI jobs for backend, PostgreSQL, Android and web.

## Run locally

```sh
npm run setup
npm run dev
```

Open http://127.0.0.1:3000. The backend requires verified accounts by default. Public samples can be explored explicitly without creating an account; samples are separate from account storage.

Without SMTP, verification, recovery and invitation messages are written to `backend/app/data/dev-outbox/*.eml` with private file permissions. Open the newest matching message locally and enter its code. This is a development mail sink, not real email delivery. Do not share those files. Codes expire after 15 minutes; invitations after 48 hours.

To recover legacy prototype records, use `backend/.venv/bin/python scripts/export_legacy.py NEW_PRIVATE_ZIP`. This preserves original notices/evidence for owner review without assigning them to an account. Reconcile legacy retention before any production data migration.

Run the persistent worker in another terminal:

```sh
PYTHONPATH=backend backend/.venv/bin/python -m app.workers.delivery
```

Android: install `output/android/docket-debug.apk`, forward port 8000 with `adb reverse tcp:8000 tcp:8000`, and use `http://127.0.0.1:8000` in Server connection. A real phone needs the development computer/server running for accounts. Local sample exploration works independently. A public installation needs the deployed HTTPS API origin.

## Production deployment preparation

1. Create an owned domain, Linux host/container platform, private managed PostgreSQL or the supplied service, encrypted volumes and secret store. Select storage region, legal entity, processors and actual backup retention. Prefer managed database backups/PITR over relying solely on a host volume.
2. Configure an SMTP provider and verified sending domain with SPF/DKIM/DMARC. Supply SMTP settings, sender and support email. Confirm codes and reminders reach real recipients, including spam handling and provider failure alerts. No provider account, DNS record or live mailbox has been provisioned by this implementation.
3. Copy `deploy/production.env.example` to ignored `.env.production`. Replace all placeholders. Generate an encryption key and store it separately from backups. Use URL-safe or URL-encoded PostgreSQL credentials. Preserve the encryption key across restarts; losing it makes encrypted records unreadable. Key rotation requires a planned re-encryption migration.
4. For S3, enable Block Public Access, restricted workload IAM, encryption, version/lifecycle policies and regional controls. Expose neither the database nor ClamAV ports. PostgreSQL attachment storage is the default if S3 is not configured; this suits a bounded pilot.
5. Run `docker compose --env-file .env.production config --quiet`, then `docker compose --env-file .env.production up --build -d`. Caddy obtains TLS for the configured domain. The gateway is the only public entry point. The API accepts forwarded headers only within the private deployment network; do not publish its port directly. ClamAV must finish loading signatures before uploads succeed.
6. Check `/api/health`, `/api/ready`, worker heartbeat and failed-job counts using `PYTHONPATH=backend python -m app.operations` inside the API container. Configure external uptime, error-rate, database, disk, scanner signature, worker age, failed reminder and queued object-deletion alerts. The repository supplies diagnostics, not an external monitoring account or paging integration.
7. Restore a backup into a separate environment, replay deletions and revoke restored sessions before allowing access. Run cross-business access tests and real-device tests. Have a security reviewer assess the pilot before accepting sensitive public workloads.

Docker/managed PostgreSQL/S3/SMTP/ClamAV were not available as running services in this workspace. Their adapters/templates are implemented; live provider and container acceptance remains a deployment gate. CI includes a PostgreSQL test matrix but has not been run on GitHub.

## Backups, deletion and incidents

SQLite development: `backend/.venv/bin/python scripts/backup.py backup /private/tmp/docket.backup`, then `... verify /private/tmp/docket.backup`. Restore only to a new path with `restore BACKUP --destination NEW_DB`. The backup is encrypted with the configured data key. Keep the key in a separate secret store.

Production: use managed encrypted PostgreSQL PITR and encrypted S3 version backups. For operator exports, pipe `pg_dump --format=custom` through a reviewed encryption tool into private backup storage. Never put database or encryption passwords in command-line arguments or backup files. Define retention and test `pg_restore` in a separate network. Include the original data encryption key through the secret manager. Keep a restricted deletion ledger outside historical snapshots and replay deletions before opening any restored snapshot. Revoke all restored sessions. Backups are not automatically pruned by the application.

For compromise: restrict gateway access, revoke sessions, rotate affected service secrets, preserve redacted operational evidence, investigate access, restore safely if needed and follow the operator's legally reviewed notification obligations. Set an owner/on-call contact and documented escalation path. Independent penetration testing and a real incident-response exercise remain required.

## Legal and product validation gates

Every supplied playbook is explicitly `2026-10-25-unreviewed`. Individual case review does not certify the library. A CA/advocate must validate notice scope, original sources, prescribed periods, service rules, office calendars, jurisdiction, financial interpretation, draft wording and revision policy. Record reviewer identity, qualifications, source citations, effective dates, approved version/checksum and review date before designating a playbook approved. Start with GST and Income Tax and keep unknown cases manual.

Finalize privacy, terms, lawful processing basis, processor contracts, consent wording, retention, support/grievance contact, applicable DPDP commencement obligations and response/deletion procedures with qualified counsel. The current public policy pages identify themselves as pilot drafts. Do not submit them unchanged as final public legal policies. No regulator authentication, automatic filing/payment, WhatsApp/SMS or live inbox ingestion is represented as configured.

## Android release and acceptance

`npm run android:build` creates a debug APK and runs native tests. `scripts/android-release.sh` requires operator-provided upload-keystore environment settings and builds an app bundle. No private release key or Play Console account has been fabricated. Use Play App Signing, store upload credentials in a secret manager and back them up separately.

Before distribution: test supported real phones and low-memory devices; email flows; multi-business access; revocation; original/scan OCR; corrupted files; SAF import/export; offline/reconnect and process death; Keystore recovery; notification permission, battery restrictions, reboot and timezone changes; data export and deletion; talkback/font scaling and small screens. Run Play pre-launch reports, publish accurate Data Safety and permission disclosures, final policy/deletion URLs, listing assets and support. Configure privacy-respecting crash monitoring with operator approval. No automatic telemetry SDK has been added.

The automated Android runtime does not replace physical-device acceptance. Live ML Kit OCR, Android Keystore, file picker and alarm delivery still require phone/emulator validation. The APK is a pilot debug build, not a Play-ready release.

## AWS deployment selected

The owner selected RDS PostgreSQL, S3 and SES. See [AWS infrastructure and staged deployment](../deploy/aws/README.md). SES API delivery uses workload IAM; no SMTP password is needed in that configuration. The template is statically validated but not deployed. Domain/Route53 ownership, AWS SSO/profile access and paid-resource approval are still required.
