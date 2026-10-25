package `in`.docket.app

import org.junit.Assert.*
import org.junit.Test
import java.time.LocalDate
import org.json.JSONObject
import org.json.JSONArray
import javax.xml.parsers.DocumentBuilderFactory

class RuleEngineTest {
    @Test fun qrOnlyScamIsBlocked() {
        val result = RuleEngine.screen("", listOf("upi://pay?pa=synthetic.qa@okicici&am=1"))
        assertEquals(100, result.score)
        assertTrue(result.flags.any { it.contains("UPI") })
    }
    @Test fun credentialsAndCoercionTriggerQuarantine() {
        assertTrue(RuleEngine.screen("Digital arrest: share your OTP").score >= 70)
    }
    @Test fun sundayExtensionRequiresExplicitChoice() {
        val strict = RuleEngine.limitation("2026-10-17", "2026-10-17", 15, false)
        val adjusted = RuleEngine.limitation("2026-10-17", "2026-10-17", 15, true)
        assertEquals(LocalDate.of(2026, 11, 1), strict.effective)
        assertEquals(LocalDate.of(2026, 11, 1), adjusted.raw)
        assertEquals(LocalDate.of(2026, 11, 2), adjusted.effective)
    }
    @Test fun periodStartsAtServiceNotIssue() {
        assertEquals(LocalDate.of(2026, 10, 30), RuleEngine.limitation("2026-10-01", "2026-10-15", 15, false).raw)
    }
    @Test(expected = IllegalArgumentException::class) fun impossibleServiceDateRejected() {
        RuleEngine.limitation("2026-10-24", "2026-10-12", 15, false)
    }
    @Test fun identifiersAreScrubbedWithoutCorruptingPlaceholders() {
        val result = RuleEngine.scrub("PAN ABCDE1234F and ABCDE1234F; GSTIN 27ABCDE1234F1Z5; Aadhaar 2345 6789 0123; Account No: 987654321012; +91 9876543210; a@example.in")
        listOf("ABCDE1234F", "27ABCDE1234F1Z5", "2345 6789 0123", "987654321012", "9876543210", "a@example.in").forEach { assertFalse(result.text.contains(it)) }
        assertEquals(6, result.count)
        val repeated = Regex("\\[REDACTED_PAN_\\d+\\]").findAll(result.text).map { it.value }.toList()
        assertEquals(2, repeated.size)
        assertEquals(repeated[0], repeated[1])
    }
    @Test fun statuteMatchingDoesNotUsePartialNumbers() {
        assertEquals(15, RuleEngine.risk("Section 173 · Other Act", 0.0, 60, false).second)
        assertEquals("RED", RuleEngine.risk("Section 138", 480000.0, 3, true).first)
    }
    @Test fun unclassifiedDocumentsAreFlaggedAndDoNotInventDemand() {
        val item = RuleEngine.analyze("Please contact us about a lease.", emptyList(), "2026-10-24", "2026-10-24", 60, false, emptyList(), "test.txt")
        assertEquals("AMBER", item.severity)
        assertEquals(0.0, item.amount, 0.0)
        assertEquals("Unclassified notice", item.title)
        assertFalse(item.forensics.optBoolean("din_format_valid"))
    }
    @Test fun sampleAuthorityAndSupplierFactsNeverTransferToUpload() {
        val template = Notice(JSONObject().put("id", "gst-asmt-10").put("severity", "AMBER").put("forensics", JSONObject()).put("triage", JSONObject().put("notice_type_title", "Input tax credit mismatch").put("issuing_authority", "Sample authority, Mumbai").put("statutory_act_and_section", "Section 61 · CGST").put("required_documents", JSONArray().put(JSONObject().put("doc_id", "doc-1").put("document_name", "Supplier invoices").put("why_needed", "Apex Fasteners and Surya Packaging").put("source_hint", "FY 2025–26, Q2")))))
        val item = RuleEngine.analyze("ASMT-10. Total demand: INR 25,000", emptyList(), "2026-10-24", "2026-10-24", 15, false, listOf(template), "notice.txt")
        assertEquals(25000.0, item.amount, 0.0)
        assertFalse(item.json.toString().contains("Mumbai"))
        assertFalse(item.json.toString().contains("Apex Fasteners"))
        assertTrue(item.draft.contains("[ISSUING_AUTHORITY]"))
    }
    @Test fun quarantinedCaseHasNoDraftOrLimitationWorkflow() {
        val item = RuleEngine.analyze("Pay now", listOf("upi://pay?pa=fraud@okicici"), "2026-10-24", "2026-10-24", 1, false, emptyList(), "scam.png")
        assertTrue(item.quarantined)
        assertNull(item.triage)
        assertNull(item.limitation)
        assertTrue(item.documents.isEmpty())
    }
    @Test fun gmailXmlIsValidAndEscaped() {
        val xml = MailRules.generate("notices+legal@example.in")
        assertTrue(xml.contains("&quot;Legal Notice&quot;"))
        val factory = DocumentBuilderFactory.newInstance()
        factory.isNamespaceAware = true
        val doc = factory.newDocumentBuilder().parse(xml.byteInputStream())
        val properties = doc.getElementsByTagNameNS("http://schemas.google.com/apps/2006", "property")
        assertEquals(3, properties.length)
    }
    @Test(expected = IllegalArgumentException::class) fun gmailXmlRejectsInjection() { MailRules.generate("bad\"/><evil>") }
}
