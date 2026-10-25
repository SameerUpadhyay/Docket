package `in`.docket.app

import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.*

data class OcrLine(val text: String, val left: Float, val top: Float, val width: Float, val height: Float, val confidence: Float?)
object OcrChecks {
    fun detectedLanguages(text: String): List<String> = buildList {
        if (Regex("[A-Za-z]").containsMatchIn(text)) add("en")
        if (Regex("[\\u0900-\\u097f]").containsMatchIn(text)) add("hi")
    }
    private val devanagari = Regex("[\\u0900-\\u097F]")
    fun merge(latin: List<OcrLine>, hindi: List<OcrLine>): List<OcrLine> {
        val merged = latin.toMutableList()
        for (line in hindi) {
            val duplicate = merged.indexOfFirst { other ->
                val overlap = max(0f, min(line.left + line.width, other.left + other.width) - max(line.left, other.left)) * max(0f, min(line.top + line.height, other.top + other.height) - max(line.top, other.top))
                overlap / max(line.width * line.height, other.width * other.height).coerceAtLeast(1f) > .6f
            }
            if (duplicate < 0) merged += line
            else if (devanagari.containsMatchIn(line.text) || (line.confidence ?: 0f) > (merged[duplicate].confidence ?: 0f)) merged[duplicate] = line
        }
        return merged.sortedWith(compareBy<OcrLine> { it.top }.thenBy { it.left })
    }
    fun page(index: Int, text: String, lines: List<OcrLine>, languages: List<String>, elapsedMs: Long, blank: Boolean = false): JSONObject {
        val scores = lines.mapNotNull { it.confidence?.times(100f)?.toDouble() }
        val flags = mutableListOf<String>()
        if (blank) flags += "VISUALLY_BLANK" else if (text.isBlank()) flags += "NO_TEXT" else if (text.length < 80) flags += "SPARSE_TEXT"
        if (scores.isEmpty() && !blank) flags += "CONFIDENCE_UNAVAILABLE"
        if (scores.isNotEmpty() && (scores.average() < 90 || scores.count { it < 90 }.toDouble() / scores.size > .1)) flags += "LOW_CONFIDENCE"
        val critical = Regex("\\d|amount|demand|section|deadline|दिनांक|राशि|धारा|दिन", RegexOption.IGNORE_CASE)
        if (lines.any { critical.containsMatchIn(it.text) && (it.confidence ?: 1f) < .95f }) flags += "CRITICAL_TEXT_NEEDS_REVIEW"
        return JSONObject().put("page", index).put("engine", "ml-kit").put("characters", text.length).put("word_count", text.split(Regex("\\s+")).count { it.isNotBlank() }).put("mean_confidence", if (scores.isEmpty()) JSONObject.NULL else scores.average()).put("low_confidence_words", scores.count { it < 90 }).put("flags", JSONArray(flags)).put("language_coverage", JSONArray(languages)).put("detected_languages", JSONArray(detectedLanguages(text))).put("qr_checked", true).put("elapsed_ms", elapsedMs)
    }
    fun report(pages: List<JSONObject>, elapsed: Long, language: String) = JSONObject().put("version", "ocr-v2").put("requested_languages", language).put("detected_languages", JSONArray(pages.flatMap { it.optJSONArray("detected_languages")?.strings().orEmpty() }.distinct())).put("page_count", pages.size).put("pages", JSONArray(pages)).put("elapsed_ms", elapsed).put("requires_review", true).put("coverage_complete", pages.all { it.optInt("characters") > 0 || it.optJSONArray("flags")?.strings()?.contains("VISUALLY_BLANK") == true }).put("quality_status", if (pages.any { it.optJSONArray("flags")?.length() != 0 }) "NEEDS_REVIEW" else "EXTRACTED_REQUIRES_FACT_CHECK").put("confidence_note", "Recognizer confidence is not measured accuracy or legal correctness.")
}
