package `in`.docket.app

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.pdf.PdfRenderer
import android.net.Uri
import android.os.ParcelFileDescriptor
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.Text
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import com.google.mlkit.vision.text.devanagari.DevanagariTextRecognizerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.common.Barcode
import kotlinx.coroutines.tasks.await
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.async
import org.json.JSONObject
import java.io.File

class DocumentReader(private val context: Context) {
    data class Extraction(val text: String, val qr: List<String>, val quality: JSONObject = JSONObject())
    suspend fun read(uri: Uri, name: String, bytes: ByteArray, language: String = "auto", progress: (Int, Int) -> Unit = { _, _ -> }): Extraction {
        require(language in listOf("auto", "en", "hi", "en-hi")) { "Choose English, Hindi or both." }
        if (name.endsWith(".txt", true)) return Extraction(bytes.toString(Charsets.UTF_8), emptyList())
        val started = android.os.SystemClock.elapsedRealtime()
        val latin = if (language != "hi") TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS) else null
        val hindi = if (language != "en") TextRecognition.getClient(DevanagariTextRecognizerOptions.Builder().build()) else null
        val qrClient = BarcodeScanning.getClient(BarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build())
        fun lines(result: Text?): List<OcrLine> = result?.textBlocks?.flatMap { it.lines }?.mapNotNull { line -> line.boundingBox?.let { box -> OcrLine(line.text, box.left.toFloat(), box.top.toFloat(), box.width().toFloat(), box.height().toFloat(), line.confidence) } } ?: emptyList()
        suspend fun inspect(image: InputImage, index: Int): Pair<Extraction, JSONObject> = coroutineScope {
            val pageStarted = android.os.SystemClock.elapsedRealtime()
            val english = async { latin?.process(image)?.await() }
            val devanagari = async { hindi?.process(image)?.await() }
            val barcode = async { qrClient.process(image).await().mapNotNull { it.rawValue } }
            val merged = OcrChecks.merge(lines(english.await()), lines(devanagari.await()))
            val text = merged.joinToString("\n") { it.text }; val qr = barcode.await()
            val page = OcrChecks.page(index, text, merged, if (language == "en-hi" || language == "auto") listOf("en", "hi") else listOf(language), android.os.SystemClock.elapsedRealtime() - pageStarted)
            Extraction(text, qr) to page
        }
        try {
            val parts = mutableListOf<String>(); val codes = mutableListOf<String>(); val pages = mutableListOf<JSONObject>()
            if (name.endsWith(".pdf", true)) {
                val temp = File.createTempFile("intake-", ".pdf", context.cacheDir)
                try {
                    temp.writeBytes(bytes)
                    ParcelFileDescriptor.open(temp, ParcelFileDescriptor.MODE_READ_ONLY).use { descriptor -> PdfRenderer(descriptor).use { renderer ->
                        require(renderer.pageCount in 1..12) { "Split PDFs into files of up to 12 pages." }
                        for (index in 0 until renderer.pageCount) {
                            require(android.os.SystemClock.elapsedRealtime() - started < 75000) { "Reading took too long. Split the document and retry; no partial case was created." }
                            progress(index + 1, renderer.pageCount)
                            renderer.openPage(index).use { page ->
                                val scale = minOf(2400f / page.width, 3400f / page.height, 3f)
                                val bitmap = Bitmap.createBitmap((page.width * scale).toInt().coerceAtLeast(1), (page.height * scale).toInt().coerceAtLeast(1), Bitmap.Config.ARGB_8888)
                                try {
                                    bitmap.eraseColor(Color.WHITE); page.render(bitmap, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
                                    val (item, metadata) = inspect(InputImage.fromBitmap(bitmap, 0), index + 1)
                                    if (item.text.isBlank() && item.qr.isEmpty()) {
                                        var blank = true
                                        loop@ for (y in 0 until bitmap.height step 12) for (x in 0 until bitmap.width step 12) { val color = bitmap.getPixel(x,y); if (Color.red(color) < 253 || Color.green(color) < 253 || Color.blue(color) < 253) { blank = false; break@loop } }
                                        require(blank) { "Page ${index + 1} is unreadable. Rescan it or paste a verified transcription; no partial case was created." }
                                        metadata.put("flags", org.json.JSONArray(listOf("VISUALLY_BLANK")))
                                    }
                                    parts += item.text; codes += item.qr; pages += metadata
                                } finally { bitmap.recycle() }
                            }
                        }
                    } }
                } finally { temp.delete() }
            } else {
                require(name.substringAfterLast('.', "").lowercase() in setOf("png", "jpg", "jpeg", "webp")) { "Choose a PDF, PNG, JPG, WEBP or UTF-8 TXT notice." }
                val dimensions = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                BitmapFactory.decodeByteArray(bytes, 0, bytes.size, dimensions)
                require(dimensions.outWidth > 0 && dimensions.outHeight > 0 && dimensions.outWidth.toLong() * dimensions.outHeight <= 30_000_000) { "Use an image smaller than 30 megapixels." }
                progress(1,1)
                val (item, metadata) = inspect(InputImage.fromFilePath(context, uri),1)
                require(item.text.isNotBlank() || item.qr.isNotEmpty()) { "No text was recognized. Use a clearer scan or a verified transcription." }
                parts += item.text; codes += item.qr; pages += metadata
            }
            require(parts.any { it.isNotBlank() } || codes.isNotEmpty()) { "No readable text was found." }
            val incomplete = pages.any { it.optInt("characters") == 0 && !it.getJSONArray("flags").strings().contains("VISUALLY_BLANK") }
            require(!incomplete || RuleEngine.screen("", codes).score >= 80) { "Some pages could not be read completely. Rescan those pages." }
            val combined = if (parts.size == 1) parts[0] else parts.mapIndexed { index, text -> "--- Page ${index + 1} ---\n$text" }.joinToString("\n\n")
            return Extraction(combined, codes.distinct(), OcrChecks.report(pages, android.os.SystemClock.elapsedRealtime() - started, language))
        } finally { latin?.close(); hindi?.close(); qrClient.close() }
    }
}
