package `in`.docket.app

import org.json.JSONObject
import java.time.LocalDate

/** OCR candidates only. Missing dates/periods never acquire statutory defaults. */
object OcrSuggestions {
    fun normalize(text: String) = text.map { c -> if (c in '\u0966'..'\u096f') ('0'.code + c.code - '\u0966'.code).toChar() else c }.joinToString("")
    fun preview(extraction: DocumentReader.Extraction): JSONObject {
        val text = normalize(extraction.text)
        val match = Regex("(?:date of issue|issue date|दिनांक|\\bDate\\b)\\s*[:=-]?\\s*(\\d{1,2})[/.-](\\d{1,2})[/.-](\\d{4})", RegexOption.IGNORE_CASE).find(text)
        val issue = match?.let { runCatching { LocalDate.of(it.groupValues[3].toInt(), it.groupValues[2].toInt(), it.groupValues[1].toInt()).toString() }.getOrNull() }
        val periods = Regex("(?<!\\d)(\\d{1,3})(?!\\d)\\s*(?:days\\b|दिन(?![\\u0900-\\u097f]))", RegexOption.IGNORE_CASE).findAll(text).map { it.groupValues[1].toInt() }.filter { it in 1..365 }.distinct().toList()
        return JSONObject().put("document_id", java.util.UUID.randomUUID().toString()).put("page_count", extraction.quality.optInt("page_count", 1)).put("structured_triage", JSONObject().put("date_of_issue_iso", issue ?: JSONObject.NULL).put("response_window_days", periods.singleOrNull() ?: JSONObject.NULL).put("core_allegation_english", "Text recognized locally. Confirm the printed dates, period and all critical numbers before creating the case.")).put("local_quality", extraction.quality)
    }
}
