package `in`.docket.app

import org.json.JSONArray
import org.json.JSONObject
import java.text.NumberFormat
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

fun JSONObject.text(key: String, fallback: String = ""): String = if (isNull(key)) fallback else optString(key, fallback)
fun JSONArray.objects(): List<JSONObject> = (0 until length()).mapNotNull { optJSONObject(it) }
fun JSONArray.strings(): List<String> = (0 until length()).map { optString(it) }
fun money(amount: Double): String = NumberFormat.getCurrencyInstance(Locale.forLanguageTag("en-IN")).apply { maximumFractionDigits = 0 }.format(amount)
fun dayLabel(iso: String): String = runCatching { LocalDate.parse(iso).format(DateTimeFormatter.ofPattern("d MMM yyyy", Locale.ENGLISH)) }.getOrDefault("Confirm date")
val indiaZone: ZoneId = ZoneId.of("Asia/Kolkata")
val demoDate: LocalDate = LocalDate.of(2026, 10, 24)

class Notice(val json: JSONObject) {
    val id: String get() = json.getString("id")
    val triage: JSONObject? get() = json.optJSONObject("triage")
    val forensics: JSONObject get() = json.getJSONObject("forensics")
    val limitation: JSONObject? get() = json.optJSONObject("limitation")
    val title: String get() = triage?.text("notice_type_title") ?: "Suspicious payment notice"
    val authority: String get() = triage?.text("issuing_authority") ?: forensics.text("sender_domain", "Unverified sender")
    val law: String get() = triage?.text("statutory_act_and_section") ?: "Quarantined for review"
    val summary: String get() = triage?.text("plain_english_summary") ?: "Strong phishing signals were detected. Do not pay, reply or share credentials."
    val hindi: String get() = triage?.text("vernacular_summary_hindi") ?: "यह नोटिस संदिग्ध है। भुगतान न करें और अपनी जानकारी साझा न करें।"
    val severity: String get() = json.text("severity", "AMBER")
    val quarantined: Boolean get() = severity == "PHISHING_SCAM"
    val state: String get() = json.text("state", "TRIAGED")
    val closed: Boolean get() = state == "SUBMITTED_CLOSED"
    val isDemo: Boolean get() = json.optBoolean("is_demo")
    val amount: Double get() = triage?.optDouble("financial_demand_inr", 0.0) ?: 0.0
    val risk: Int get() = json.optInt("deterministic_risk_score")
    val deadline: String get() = limitation?.text("effective_legal_deadline") ?: ""
    val days: Long? get() = runCatching { java.time.temporal.ChronoUnit.DAYS.between(if (isDemo) demoDate else LocalDate.now(indiaZone), LocalDate.parse(deadline)) }.getOrNull()
    val documents: List<JSONObject> get() = triage?.optJSONArray("required_documents")?.objects() ?: emptyList()
    val collected: Int get() = documents.count { it.optBoolean("is_collected") }
    val draft: String get() = json.text("draft_reply", triage?.text("draft_reply_template") ?: "")
    val redactedText: String get() = json.text("redacted_ocr_excerpt")
    val reviewNotes: List<String> get() = json.optJSONArray("review_notes")?.strings() ?: emptyList()
    val flags: List<String> get() = forensics.optJSONArray("scam_flags")?.strings() ?: emptyList()
    val service: String get() = when {
        quarantined -> "Security"
        Regex("epf|esic|14b|7q", RegexOption.IGNORE_CASE).containsMatchIn(law) -> "Labour"
        Regex("138|negotiable|lease|private", RegexOption.IGNORE_CASE).containsMatchIn(law) -> "Legal"
        Regex("gst|income tax|143", RegexOption.IGNORE_CASE).containsMatchIn(law) -> "Tax"
        else -> "Other"
    }
    fun duplicate(): Notice = Notice(JSONObject(json.toString()))
}

fun stateLabel(state: String) = when (state) {
    "TRIAGED" -> "Ready to review"
    "DOCS_GATHERING" -> "Gathering evidence"
    "DRAFT_READY" -> "Ready for a draft"
    "CA_ESCALATED" -> "Advisor review"
    "SUBMITTED_CLOSED" -> "Closed"
    "PHISHING_QUARANTINED" -> "Quarantined"
    else -> "New notice"
}
fun severityLabel(severity: String) = when (severity) {
    "RED" -> "Priority"
    "AMBER" -> "Action needed"
    "GREEN" -> "Routine"
    else -> "Quarantined"
}
