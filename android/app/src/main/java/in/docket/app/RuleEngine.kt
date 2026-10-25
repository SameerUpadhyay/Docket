package `in`.docket.app

import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDate
import java.time.temporal.ChronoUnit
import java.util.UUID

/** Device-side screening. It does not authenticate a document or decide liability. */
object RuleEngine {
    data class Screening(val score: Int, val flags: List<String>)
    data class Dates(val raw: LocalDate, val effective: LocalDate)
    data class Redaction(val text: String, val count: Int)
    fun limitation(issue: String, service: String, days: Int, allowSunday: Boolean): Dates {
        val issued = LocalDate.parse(issue)
        val received = LocalDate.parse(service)
        require(!received.isBefore(issued)) { "The receipt date cannot precede the issue date." }
        require(days in 1..365) { "Enter a response period between 1 and 365 days." }
        val raw = received.plusDays(days.toLong())
        val effective = if (allowSunday && raw.dayOfWeek.value == 7) raw.plusDays(1) else raw
        return Dates(raw, effective)
    }
    fun screen(text: String, qr: List<String> = emptyList()): Screening {
        val all = text + "\n" + qr.joinToString("\n")
        var score = 0
        val flags = mutableListOf<String>()
        listOf(
            Triple("upi://pay\\?|[\\w.\\-]+@(?:okicici|okaxis|oksbi|okhdfcbank|ybl|paytm|upi)\\b", 100, "A direct UPI payment or private payment address was detected."),
            Triple("\\b0x[a-f0-9]{40}\\b|\\bbc1[a-z0-9]{25,60}\\b", 100, "A cryptocurrency payment address was detected."),
            Triple("share\\s+your\\s+(otp|password|pin)|enter\\s+upi\\s+pin|anydesk|teamviewer|rustdesk", 90, "The text requests credentials or remote access."),
            Triple("digital\\s+arrest|join\\s+skype\\s+investigation|scan\\s+(the|this)\\s+qr\\s+code\\s+to\\s+(pay|settle)", 85, "Scam coercion or a QR payment instruction was detected.")
        ).forEach { (pattern, points, message) -> if (Regex(pattern, RegexOption.IGNORE_CASE).containsMatchIn(all)) { score += points; flags += message } }
        Regex("(?:https?://)([a-z0-9.\\-]+)", RegexOption.IGNORE_CASE).findAll(all).forEach { match ->
            val domain = match.groupValues[1].lowercase()
            val governmentClaim = Regex("\\b(gst|cgst|cbic|income tax|epfo|esic)\\b", RegexOption.IGNORE_CASE).containsMatchIn(text)
            if (governmentClaim && !domain.endsWith(".gov.in") && !domain.endsWith(".nic.in") && domain != "gstn.org.in") { score += 35; flags += "An external website needs independent review: $domain" }
        }
        return Screening(score.coerceAtMost(100), flags.distinct())
    }
    fun scrub(text: String): Redaction {
        var count = 0
        var result = text
        val tokens = mutableMapOf<String, String>()
        val patterns = linkedMapOf(
            "GSTIN" to "\\b\\d{2}[A-Z]{5}\\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]\\b",
            "PAN" to "\\b[A-Z]{5}\\d{4}[A-Z]\\b",
            "BANK" to "\\b(?:A/C|Account\\s*(?:No\\.?|Number)|Acct)[\\s:#-]*\\d{9,18}\\b",
            "AADHAAR" to "\\b[2-9]\\d{3}[ -]?\\d{4}[ -]?\\d{4}\\b",
            "MOBILE" to "(?<!\\w)(?:\\+91[ -]?)?[6-9]\\d{9}\\b",
            "EMAIL" to "\\b[\\w.+-]+@[\\w.\\-]+\\.[A-Za-z]{2,}\\b"
        )
        patterns.forEach { (label, pattern) -> result = Regex(pattern, RegexOption.IGNORE_CASE).replace(result) { match -> tokens.getOrPut(match.value) { count++; "[REDACTED_${label}_$count]" } } }
        return Redaction(result, count)
    }
    fun risk(law: String, amount: Double, days: Long, criminal: Boolean, coercive: Boolean = false): Pair<String, Int> {
        val high = Regex("\\b(73|74|138|148|45a|7a|14b)\\b|drc-01|reg-17", RegexOption.IGNORE_CASE).containsMatchIn(law)
        var score = if (high) 40 else if (Regex("\\b61\\b|asmt-10|139\\(9\\)", RegexOption.IGNORE_CASE).containsMatchIn(law)) 25 else 10
        score += when { days <= 3 -> 30; days <= 7 -> 22; days <= 15 -> 12; else -> 5 }
        score += when { amount >= 250000 -> 20; amount >= 25000 -> 12; amount > 0 -> 6; else -> 0 }
        if (criminal || coercive) score += 25
        score = score.coerceAtMost(99)
        return (if (score >= 65 || criminal) "RED" else if (score >= 32) "AMBER" else "GREEN") to score
    }
    fun analyze(text: String, qr: List<String>, issue: String, service: String, window: Int, sunday: Boolean, templates: List<Notice>, filename: String): Notice {
        require(text.isNotBlank() || qr.isNotEmpty()) { "No readable notice text or QR code was found." }
        require(text.length <= 200000) { "The extracted text exceeds the 200,000 character limit." }
        val dates = limitation(issue, service, window, sunday)
        val screening = screen(text, qr)
        val redaction = scrub(text + if (qr.isEmpty()) "" else "\nDecoded QR payloads:\n" + qr.joinToString("\n"))
        val quarantine = screening.score >= 70
        val patterns = listOf("gst-asmt-10" to "asmt.?10|gstr.?(2b|3b)|input tax credit", "cheque-section-138" to "section\\s*138|cheque|dishonou?r", "income-tax-143" to "143\\s*\\(1\\)|income tax|itr.3", "epfo-14b" to "epfo|14b|provident fund|7q")
        val match = patterns.firstOrNull { Regex(it.second, RegexOption.IGNORE_CASE).containsMatchIn(text) }?.first
        val base = templates.find { it.id == match }
        val amount = Regex("(?:total\\s+(?:demand|amount)|amount\\s+(?:demanded|payable)|demand\\s+amount)\\s*[:=]?\\s*(?:INR|Rs\\.?|₹)?\\s*([\\d,]+(?:\\.\\d{1,2})?)", RegexOption.IGNORE_CASE).find(text)?.groupValues?.get(1)?.replace(",", "")?.toDoubleOrNull() ?: 0.0
        val law = base?.law ?: "Statute requires professional confirmation"
        val criminal = Regex("section\\s*138|criminal\\s+proceedings", RegexOption.IGNORE_CASE).containsMatchIn(text)
        val coercive = Regex("bank\\s+(?:account\\s+)?(?:freeze|attachment)|e.way\\s+bill\\s+block", RegexOption.IGNORE_CASE).containsMatchIn(text)
        val (initialTier, risk) = risk(law, amount, ChronoUnit.DAYS.between(LocalDate.now(indiaZone), dates.effective), criminal, coercive)
        val tier = if (quarantine) "PHISHING_SCAM" else if (base == null && initialTier == "GREEN") "AMBER" else initialTier
        val docs = base?.documents?.map { doc ->
            JSONObject(doc.toString()).apply {
                put("is_collected", false); remove("attachment_name"); remove("local_file")
                listOf("document_name", "why_needed", "source_hint").forEach { key -> put(key, text(key).replace("Apex Fasteners and Surya Packaging", "the relevant suppliers").replace("FY 2025–26, Q2", "the relevant period").replace("AY 2026–27", "the relevant assessment year").replace("April–July 2026", "the relevant contribution periods")) }
            }
        } ?: listOf(JSONObject().put("doc_id", "doc-1").put("document_name", "Original notice and proof of receipt").put("why_needed", "A professional needs these to establish the applicable response period.").put("source_hint", "Original notice, email or postal delivery record.").put("is_collected", false))
        val triage = JSONObject().apply {
            put("issuing_authority", "Issuing authority requires confirmation")
            put("notice_type_title", base?.title ?: "Unclassified notice")
            put("statutory_act_and_section", law)
            put("plain_english_summary", if (base != null) "This appears to relate to ${base.title.lowercase()}. Confirm the allegation and amount against the original. The local playbook organizes your response; it does not determine liability." else "This notice does not match a supported playbook. Ask an advocate or CA to confirm the authority, law and required response.")
            put("vernacular_summary_hindi", "मूल नोटिस से अधिकारी, आरोप, राशि और जवाब की अवधि की पुष्टि करें। जरूरत पड़ने पर वकील या CA से सलाह लें।")
            put("financial_demand_inr", amount); put("required_documents", JSONArray(docs))
            put("has_criminal_or_arrest_clause", criminal); put("has_bank_freeze_or_eway_block_threat", coercive)
            put("recommended_professional", if (criminal) "Advocate" else "Chartered Accountant / Advocate")
            put("professional_reason", "Confirm the facts and applicable response period before taking action.")
            put("draft_reply_template", "To,\n[ISSUING_AUTHORITY]\n\nSubject: Response to [NOTICE_REFERENCE]\n\nRespected Sir / Madam,\n\nWe acknowledge receipt on [DATE_RECEIVED]. Please consider the following verified records:\n\n1. [FACTUAL_EXPLANATION]\n2. [RECONCILIATION_OR_PAYMENT_DETAILS]\n3. [EVIDENCE_INDEX]\n\nWe request an opportunity to clarify any remaining issues.\n\nYours faithfully,\n[AUTHORIZED_SIGNATORY]\n[BUSINESS_NAME]\n[DATE]\n\nDRAFT FOR PROFESSIONAL REVIEW. Verify all facts before signing.")
        }
        return Notice(JSONObject().apply {
            put("id", UUID.randomUUID().toString().take(12)); put("ingested_at", java.time.Instant.now().toString())
            put("ingestion_channel", "ANDROID_LOCAL"); put("state", if (quarantine) "PHISHING_QUARANTINED" else "TRIAGED")
            put("severity", tier); put("deterministic_risk_score", if (quarantine) 100 else if (base == null) risk.coerceAtLeast(32) else risk)
            put("is_demo", false); put("analysis_mode", "android-local-playbook"); put("original_filename", filename)
            put("redacted_ocr_excerpt", redaction.text); put("pii_tokens_redacted_count", redaction.count)
            put("forensics", JSONObject().put("verdict", if (quarantine) "PHISHING_SCAM" else "SUSPICIOUS_UNVERIFIED").put("fraud_risk_score", screening.score).put("safe_to_process", !quarantine).put("scam_flags", JSONArray(screening.flags)).put("verification_note", "Local heuristic screening only. Mail signatures and DIN have not been verified."))
            if (!quarantine) {
                put("triage", triage)
                put("limitation", JSONObject().put("date_of_issue", issue).put("date_of_service", service).put("statutory_window_days", window).put("raw_expiry_date", dates.raw.toString()).put("effective_legal_deadline", dates.effective.toString()).put("holiday_rollover_applied", dates.raw != dates.effective).put("calculation_note", "Planning estimate. Confirm service, prescribed period and the relevant office calendar."))
            }
            put("review_notes", JSONArray(listOf("Dates and period were supplied by the uploader.", "A zero amount means no labelled demand was extracted; check the original.", "Regex redaction does not remove every name, address or identifier.", "OCR can misread dates and amounts. Verify the source.") + if (dates.raw != dates.effective) listOf("Sunday adjustment was explicitly selected; confirm legal applicability.") else emptyList()))
        })
    }
}
