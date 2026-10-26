package `in`.docket.app

import android.content.Context
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.graphics.pdf.PdfDocument
import java.io.ByteArrayOutputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

class CaseExporter(private val context: Context, private val store: NoticeStore) {
    fun bytes(notice: Notice, type: String): ByteArray = when (type) {
        "reply" -> { require(!notice.quarantined) { "Quarantined notices do not have replies." }; pdf(notice.draft, "Reply draft · for review") }
        "report" -> pdf(brief(notice), "Case brief · for review")
        else -> {
            val output = ByteArrayOutputStream()
            ZipOutputStream(output).use { zip ->
                fun entry(name: String, bytes: ByteArray) { zip.putNextEntry(ZipEntry(name)); zip.write(bytes); zip.closeEntry() }
                entry("case-brief.pdf", pdf(brief(notice), "Case brief · for review"))
                entry("case-brief.txt", brief(notice).toByteArray())
                entry("dossier.json", notice.json.toString(2).toByteArray())
                entry("redacted-notice.txt", notice.redactedText.toByteArray())
                if (notice.json.optBoolean("source_capture")) entry("original-captured-notice.pdf", store.cameraOriginal(notice.id))
                if (!notice.quarantined) entry("saved-reply.txt", notice.draft.toByteArray())
                notice.documents.forEachIndexed { index, doc -> store.evidenceBytes(doc)?.let { bytes -> entry("evidence/${index + 1}.${doc.text("attachment_name").substringAfterLast('.', "bin").filter { it.isLetterOrDigit() }}", bytes) } }
            }
            output.toByteArray()
        }
    }
    fun brief(notice: Notice): String = buildString {
        appendLine(notice.title)
        appendLine("Case: ${notice.id} | ${stateLabel(notice.state)}")
        if (notice.isDemo) appendLine("FICTIONAL DEMO CASE · reference date 24 October 2026")
        appendLine("Risk: ${severityLabel(notice.severity)} · ${notice.risk}/100")
        appendLine("Screening: ${notice.forensics.text("verification_note", "Not independently authenticated")}")
        appendLine(); appendLine(notice.authority); appendLine(notice.law)
        appendLine(); appendLine(notice.summary)
        if (!notice.quarantined) {
            appendLine("Amount to review: ${money(notice.amount)}")
            appendLine("Issued: ${notice.limitation?.text("date_of_issue")}")
            appendLine("Received: ${notice.limitation?.text("date_of_service")}")
            appendLine("Raw expiry: ${notice.limitation?.text("raw_expiry_date")}")
            appendLine("Planning deadline: ${notice.deadline}")
            appendLine("Confirm service, applicable period and office closure before relying on this date.")
            appendLine(); appendLine("EVIDENCE")
            notice.documents.forEach { appendLine("[${if (it.optBoolean("is_collected")) "x" else " "}] ${it.text("document_name")}${it.text("attachment_name").takeIf(String::isNotBlank)?.let { name -> " — $name" }.orEmpty()}") }
            appendLine(); appendLine("SAVED REPLY DRAFT"); appendLine(notice.draft)
        } else { appendLine(); appendLine("DO NOT PAY OR REPLY"); notice.flags.forEach(::appendLine) }
        appendLine(); appendLine("REVIEW NOTES"); notice.reviewNotes.forEach(::appendLine)
        appendLine(); appendLine("Prepared for review. No response, payment or report has been submitted.")
    }
    private fun pdf(content: String, subtitle: String): ByteArray {
        val document = PdfDocument()
        val ink = Color.rgb(27, 54, 93)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { textSize = 11f; color = ink; typeface = Typeface.create("sans-serif", Typeface.NORMAL) }
        var number = 0
        var page: PdfDocument.Page? = null
        var y = 0f
        fun start() {
            page?.let { document.finishPage(it) }
            number++
            page = document.startPage(PdfDocument.PageInfo.Builder(595, 842, number).create())
            val canvas = page!!.canvas
            paint.textSize = 22f; paint.typeface = Typeface.create("sans-serif", Typeface.BOLD)
            canvas.drawText("Docket", 40f, 45f, paint)
            paint.textSize = 9f; paint.typeface = Typeface.create("sans-serif", Typeface.NORMAL)
            canvas.drawText(subtitle, 40f, 63f, paint)
            paint.color = Color.rgb(212, 175, 55); paint.strokeWidth = 2f
            canvas.drawLine(40f, 76f, 555f, 76f, paint)
            paint.color = Color.rgb(91, 103, 119); paint.textSize = 8f
            canvas.drawText("Professional review required · No response has been filed", 40f, 814f, paint)
            canvas.drawText(number.toString(), 544f, 814f, paint)
            paint.color = ink; paint.textSize = 11f; y = 100f
        }
        start()
        content.lines().forEach { paragraph ->
            if (paragraph.isBlank()) { y += 8f; return@forEach }
            var remaining = paragraph
            while (remaining.isNotEmpty()) {
                if (y > 785f) start()
                var count = paint.breakText(remaining, true, 515f, null)
                if (count < remaining.length && count > 0) {
                    val space = remaining.lastIndexOf(' ', count - 1)
                    if (space > count / 2) count = space
                }
                count = count.coerceAtLeast(1)
                page!!.canvas.drawText(remaining.take(count), 40f, y, paint)
                remaining = remaining.drop(count).trimStart(); y += 16f
            }
        }
        page?.let { document.finishPage(it) }
        return ByteArrayOutputStream().also { document.writeTo(it); document.close() }.toByteArray()
    }
}

object MailRules {
    fun generate(address: String, sourceEmail: String = ""): String {
        require(Regex("[A-Za-z0-9._+\\-]+@[A-Za-z0-9.\\-]+\\.[A-Za-z]{2,}").matches(address)) { "Enter a valid forwarding address." }
        if (sourceEmail.isNotEmpty()) {
            require(Regex("[A-Za-z0-9._+\\-]+@[A-Za-z0-9.\\-]+\\.[A-Za-z]{2,}").matches(sourceEmail)) { "Enter the Gmail account you are importing into." }
            fun mailbox(value: String): String {
                val (local, domain) = value.lowercase(java.util.Locale.ROOT).split('@')
                return if (domain == "gmail.com" || domain == "googlemail.com") local.substringBefore('+').replace(".", "") + "@gmail.com" else "$local@$domain"
            }
            require(mailbox(address) != mailbox(sourceEmail)) { "Gmail cannot forward to itself. Use a separate, verified receiving address. Dot and plus aliases still use the same Gmail mailbox." }
        }
        fun escaped(text: String) = text.replace("&", "&amp;").replace("\"", "&quot;").replace("'", "&apos;").replace("<", "&lt;").replace(">", "&gt;")
        val query = "from:(incometax.gov.in OR cpc.incometax.gov.in OR gst.gov.in OR gstn.org.in OR cbic.gov.in OR tdscpc.gov.in OR icegate.gov.in OR mca.gov.in OR epfindia.gov.in OR shramsuvidha.gov.in OR esic.gov.in OR esic.nic.in OR msme.gov.in OR fssai.gov.in OR itshubham3901@gmail.com OR upadhyaysameer09@gmail.com) OR subject:(\"Show Cause Notice\" OR \"Demand Notice\" OR \"Legal Notice\" OR \"Section 138\" OR \"DRC-01\" OR \"ASMT-10\" OR \"REG-17\" OR \"Intimation u/s\" OR \"कारण बताओ नोटिस\" OR \"विधिक नोटिस\")"
        return """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:apps="http://schemas.google.com/apps/2006">
<title>Docket notice filter</title><updated>${java.time.Instant.now()}</updated>
<entry><category term="filter"/><title>Forward matching legal notices</title>
<apps:property name="hasTheWord" value="${escaped(query)}"/>
<apps:property name="forwardTo" value="${escaped(address)}"/>
<apps:property name="label" value="Docket-Notices"/></entry></feed>"""
    }
}
