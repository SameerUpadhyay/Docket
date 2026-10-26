# Selective email forwarding

Email intake is available in **Account → Email** in the web companion and native Android app. It receives messages forwarded by a mailbox rule or by hand. Docket does not connect to Gmail, request OAuth mailbox scopes, poll your Gmail inbox, confirm forwarding links, send replies, file responses, or make payments.

## Try the local flow

1. Start the API and web app, then sign in with a verified business-owner account.
2. Open Account → Email, review the sharing explanation and enable a local preview receiving address.
3. Expand **Local test messages · fictional data**. Try Google confirmation, GST + PDF, a manual legal forward, and a spoofed payment demand. Web updates arrive through an authenticated event stream; Android polls this app's event metadata while visible.
4. Open Notices. Samples are labelled and remain separate from real case workflows. Actual received notices require confirmation of issue date, proof of service and response period before any deadline or reminder is planned.

Without provider configuration, the generated `inbound.example.invalid` address is a preview. It cannot receive Internet mail. The test controls are owner-only and unavailable in production. Simulated confirmation codes never authenticate a real mailbox or sender.

Gmail confirmation and filter export are disabled during local preview. After connecting a real receiving provider, replace the preview address in Account → Email, add the new address in Gmail's Forwarding settings, complete verification, and then download and import the selective filter. Keep forwarding for all messages disabled.

If Gmail reports **“Invalid forwarding address. You cannot specify your own email address,”** the XML points back to the mailbox you are importing into. Use Docket's separate receiving address instead. Gmail dot variants, plus tags and `googlemail.com` variants still refer to the same Gmail mailbox. The device-only manual filter now asks for both the source mailbox and a separate destination and rejects these loops; forwarding to an ordinary second mailbox does not itself enable Docket ingestion. [Google's forwarding instructions](https://support.google.com/mail/answer/10957?hl=en).

## Connect a receiving service

Use a receiving domain you control or an existing Postmark inbound address. Supply settings through the environment/secret manager before starting the API and email worker. The application never provisions a provider account or DNS records itself.

### Dedicated AgentMail inbox (personal Gmail signup supported)

Sign up at https://console.agentmail.to with Google, create a dedicated `@agentmail.to` inbox, and create an API key scoped to **that single inbox** with **Read-only** access. A key can expire; renew it before its expiry to keep receiving. This reads only mail forwarded to the dedicated provider inbox, never the source Gmail account. The free provider plan currently includes three inboxes and 3,000 emails/month (100/day); check the provider dashboard for current limits. The receiving provider stores the forwarded messages under its own retention and privacy policy.

```text
INBOUND_EMAIL_PROVIDER=agentmail
INBOUND_AGENTMAIL_ADDRESS=your-dedicated-inbox@agentmail.to
AGENTMAIL_API_KEY=<inbox-scoped-read-only-key>
```

For Windows development, put these values in the ignored `.secrets/inbound.env` file; `scripts/dev.ps1` loads only the allowlisted receiving settings. Do not paste a key into chat, a client-side setting or a tracked file. Restart the app after configuration. For a deployment, supply them through its secret manager/environment and keep the email worker running.

Open Account → Email and enable receiving, or replace a preview address. One dedicated provider inbox belongs to only one Docket workspace. The address is fixed: to replace it, configure another dedicated inbox first. Disabling/re-enabling starts a new receiving period and does not import earlier provider mail. Removing a case does not delete its provider copy; a read-only key cannot send, modify or delete anything at AgentMail.

The receiver makes outbound HTTPS calls about every 15 seconds; there is no public webhook, tunnel, DNS requirement or Gmail OAuth permission. Initial and backlog scans can take longer. The worker imports provider-created messages from the active receiving period, up to the last 30 days. It resumes paginated scans, deduplicates accepted/rejected/deleted receipts, preserves the original MIME for signature verification, and passes attachments through the existing bounded local screening pipeline. Provider-supplied raw download URLs are restricted to HTTPS cdn.agentmail.to or CloudFront with no redirects and never receive the API key. Connection errors appear in Account → Email. Keep the computer and Docket server running; use a continuously running deployment for reliable unattended delivery.

Complete Gmail's forwarding verification for this receiving address, leave all-mail forwarding disabled, then download and import a new selective XML rule. The app never marks real Gmail confirmation as completed automatically.

[AgentMail signup and quickstart](https://www.agentmail.to/docs/quickstart), [pricing](https://www.agentmail.to/pricing), [raw MIME API](https://www.agentmail.to/docs/api-reference/inboxes/messages/get-raw).

### Direct Postmark integration

```text
INBOUND_EMAIL_PROVIDER=postmark
INBOUND_POSTMARK_USER=docket-inbound
INBOUND_POSTMARK_PASSWORD=<32-or-more-random-characters-from-your-secret-manager>
INBOUND_EMAIL_DOMAIN=inbound.your-domain.example
```

Alternatively, omit `INBOUND_EMAIL_DOMAIN` and set `INBOUND_POSTMARK_ADDRESS` to your actual `serverhash@inbound.postmarkapp.com`. Workspace addresses then use `serverhash+u_<random-token>@inbound.postmarkapp.com`. Set the inbound message stream's webhook to the HTTPS `/api/v1/email/inbound-webhook` endpoint, with the matching HTTP Basic credentials. Set `RawEmailEnabled=true` on the Postmark server to supply original RFC822 content for signature verification. Follow Postmark's instructions for the actual inbound domain/MX configuration; the example domain above is a placeholder.

Successful Postmark deliveries return HTTP **200**, as required by its retry protocol. The payload is accepted only after an encrypted delivery record commits. Raw content is removed from the queue after processing. Duplicate provider MessageIDs are idempotent within a route; changing content under the same ID is rejected. [Postmark inbound webhook documentation](https://postmarkapp.com/developer/webhooks/inbound-webhook), [server settings](https://postmarkapp.com/developer/api/server).

### Signed provider/SMTP adapter

```text
INBOUND_EMAIL_PROVIDER=hmac
INBOUND_EMAIL_DOMAIN=inbound.your-domain.example
INBOUND_WEBHOOK_SECRET=<32-or-more-random-characters-from-your-secret-manager>
```

Your trusted adapter must send a Postmark-shaped JSON body with `OriginalRecipient` set to the SMTP envelope recipient, a stable `MessageID`, and `RawEmail` as the original RFC822 text or base64-encoded MIME. Normalized `From`, `Subject`, `TextBody`, `HtmlBody`, `Headers`, and base64 `Attachments` are also supported. When MIME is present, parsing uses its actual sender/body/attachments; JSON fields cannot substitute different content under a valid signature.

Authenticate the exact request bytes with:

```text
X-Docket-Timestamp: <Unix-seconds>
X-Docket-Signature: v1=<hex HMAC-SHA256(secret, timestamp + "." + raw-request-body)>
```

The timestamp must be within five minutes. Successful accepted deliveries return HTTP 202. A generic SendGrid/Cloudflare webhook must be normalized and signed by this trusted adapter; those providers' native signatures and multipart formats are not implicitly supported by the Postmark JSON parser. Never put the provider secret into the browser or Android app.

## Worker and deployment

The development API starts an inline recovery loop. Accepted deliveries also schedule immediate background processing. Configure `INBOUND_INLINE_WORKER=0` in production and run:

```sh
PYTHONPATH=backend backend/.venv/bin/python -m app.workers.email_ingestion
```

On Windows, dot-source `scripts/tools-env.ps1`, set `PYTHONPATH=backend`, and run `backend/.venv/Scripts/python.exe -X utf8 -m app.workers.email_ingestion`. The Compose template includes `email-worker`, with local OCR, private database and ClamAV connectivity. Deploy the worker alongside the API in other hosting arrangements. Production file processing fails closed while malware screening is unavailable and retries transient screening failures.

Workers claim deliveries using database leases and recheck the receiving route before committing a case. Routes have high-entropy random tokens, exact recipient matching, encrypted addresses, and hashed lookup keys. Disabling or replacing an address cancels its queued work and clears forwarding codes. Update/remove the corresponding Gmail rule too. Existing cases remain until explicitly deleted.

## Forwarding setup

Add the current address in Gmail forwarding settings. If the original confirmation message has a valid aligned Google DKIM signature or a valid ARC chain from a configured trusted sealer, Docket shows its actual confirmation code/link for ten minutes. There is no fallback code for real mail. The user completes confirmation in Gmail and records that action in Docket before downloading the XML filter. A provider that strips original MIME may require completing confirmation through its own message viewer instead.

The XML uses explicit sender criteria and legal subject triggers, including Hindi terms. It does not alter spam handling. Users can inspect the exact search query in the setup screen. Keyword/sender matches can include unrelated or personal mail and never establish authenticity. Review matches before enabling the rule; keep all-mail forwarding disabled.

## Forensics and privacy

- Original DKIM is verified against DNS TXT keys with bounded lookups. ARC requires a valid chain and a configured trusted latest sealer (`INBOUND_TRUSTED_ARC_SEALERS=google.com` by default). Signed domains must align with the claimed sender. A manual forward's quoted `From:` remains a claim even if the forwarder's own signature is valid. Plain `Authentication-Results`, `X-Forwarded-*`, and copied ARC strings do not establish verification. SPF is not recomputed from a forwarded MIME file; only trusted validated ARC observations are reported. Mail provenance does not authenticate a legal notice or its factual claims. [dkimpy verification library](https://pypi.org/project/dkimpy/).
- Every attachment is checked before OCR/model use. Intake is bounded to 12 MB of HTTP data, 8 MB decoded content, six attachments and twelve combined document pages. Executables, disguised types, active/encrypted PDFs and unsupported attached-email nesting are rejected/isolated. The development runtime uses file/content checks; production additionally requires the configured malware scanner.
- Every accepted attachment is read locally, including English/Hindi OCR and QR screening. Email attachment images are never sent to cloud OCR. Payment redirection and unsafe attachments quarantine the message and suppress external summaries. Optional cloud processing for manually uploaded documents retains its separate existing consent.
- PAN, GSTIN, Aadhaar, labelled bank accounts, IFSC, mobile numbers and email addresses are masked locally across subject/body/extracted attachment text before optional summaries. Regex masking can miss identifiers. External summaries require the workspace owner's separate existing AI consent; simulated messages never call external AI.
- The reversible identifier map is encrypted, scoped to its case/workspace, and accessible only to owners/editors for 24 hours. Browser reveal is explicit and held in component memory. Reviewers cannot fetch the map. Original attachments are retained encrypted only when the existing original-retention choice is enabled. Normalized text is stored as a redacted, encrypted case.
- Verification codes expire after ten minutes; events and identifier maps after 24 hours. Pending encrypted content expires after 24 hours, and completed receipt metadata after 30 days. The worker removes expired records; access checks enforce expiry. The queue is bounded to 20 pending messages per business and 200 overall, returning 429 when full so the provider can retry. Provider-side retention and encrypted infrastructure backups follow their own documented operator/provider policies.
- Streams and polling endpoints use the normal session and selected workspace. Streams recheck session validity and membership throughout their lifetime, replay durable event IDs after reconnecting, and never expose codes, mail bodies or identifier maps in notification payloads. They do not use receiving tokens as user authentication. No sub-500ms delivery guarantee is asserted.
- Case deletion removes its identifier map and invalidates receipt references. Account deletion removes owned routes, pending content, codes, events and maps. Account export includes delivery metadata and unexpired identifier maps inside the authenticated owner's export.

## Checks

The email suite tests signed/tampered mail, ARC trust/alignment, forged headers, private verification codes, webhook authentication, workspace roles, duplicate receipts, durable recovery, consent withdrawal, attachment checks, local bilingual PDF/QR extraction, PII round trips/expiry, export/deletion, stream revocation, and production simulator blocking.

```powershell
. ./scripts/tools-env.ps1
& backend/.venv/Scripts/python.exe -X utf8 -m pytest -q backend/tests
npm.cmd run typecheck
npm.cmd run build
npm.cmd run android:build:windows
```

Real provider delivery, domain/MX propagation, Google forwarding confirmation, and physical Android camera/Keystore operation still require operator credentials and an actual configured environment/device. Local simulations and synthetic test fixtures are labelled accordingly.

## Demonstration senders

The Gmail forwarding search additionally matches `itshubham3901@gmail.com` and `upadhyaysameer09@gmail.com`. Messages from either address match without a notice keyword in the subject; Gmail filters therefore forward all matching messages from these two senders. Use these addresses to send selected demonstration documents to the source mailbox `redwire001@gmail.com`; the selective rule forwards them to `docketinbox@agentmail.to`. This changes forwarding criteria only. Sender signature verification, attachment checks, PII redaction and fact/deadline confirmation still apply. After changing criteria, download a fresh XML rule in Account → Email and replace the older rule in Gmail. The native manual XML generator uses the same search query.
