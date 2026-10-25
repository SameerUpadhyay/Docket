package `in`.docket.app
import org.junit.Assert.*
import org.junit.Test

class OcrChecksTest {
    @Test fun overlappingMixedScriptLineIsMergedWithoutDeletingOtherLines() {
        val english = listOf(OcrLine("GSTR-3B mismatch", 10f,10f,200f,30f,.95f),OcrLine("DIN ABC123",10f,60f,150f,20f,.99f))
        val hindi = listOf(OcrLine("GSTR-3B मिलान में अंतर",10f,10f,205f,30f,.94f))
        val merged=OcrChecks.merge(english,hindi)
        assertEquals(2,merged.size);assertTrue(merged[0].text.contains("अंतर"));assertTrue(merged[1].text.contains("DIN"))
    }
    @Test fun aPartialDetectionCannotReplaceACompleteSourceLine() {
        val complete=OcrLine("Demand INR 160000",0f,0f,400f,25f,.8f)
        val fragment=OcrLine("Demand",0f,0f,80f,25f,.99f)
        assertTrue(OcrChecks.merge(listOf(complete),listOf(fragment)).any { it.text==complete.text })
    }
    @Test fun devanagariCandidatesHaveNoInventedDefaults() {
        val result=OcrSuggestions.preview(DocumentReader.Extraction("दिनांक: १५/१०/२०२६\nप्राप्ति के १५ दिन के भीतर उत्तर दें।",emptyList()))
        assertEquals("2026-10-15",result.getJSONObject("structured_triage").getString("date_of_issue_iso"))
        assertEquals(15,result.getJSONObject("structured_triage").getInt("response_window_days"))
        val unknown=OcrSuggestions.preview(DocumentReader.Extraction("दिनांक अज्ञात; कार्यालय से संपर्क करें।",emptyList())).getJSONObject("structured_triage")
        assertTrue(unknown.isNull("date_of_issue_iso"));assertTrue(unknown.isNull("response_window_days"))
    }
    @Test fun conflictingResponsePeriodsRemainUnresolved() {
        val fields=OcrSuggestions.preview(DocumentReader.Extraction("The statute says 30 days; pay within 15 days.",emptyList())).getJSONObject("structured_triage")
        assertTrue(fields.isNull("response_window_days"))
    }
    @Test fun confidenceIsNotInventedWhenRecognizerDoesNotProvideIt() {
        val page=OcrChecks.page(1,"A sufficiently long statement from a notice that still needs fact checking.",listOf(OcrLine("Section 73",0f,0f,100f,20f,null)),listOf("en"),50)
        assertTrue(page.isNull("mean_confidence"));assertTrue(page.getJSONArray("flags").strings().contains("CONFIDENCE_UNAVAILABLE"))
        assertTrue(OcrChecks.report(listOf(page),50,"en").getBoolean("requires_review"))
    }
}
