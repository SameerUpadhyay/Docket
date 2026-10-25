package `in`.docket.app

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.media.ExifInterface
import java.io.File
import java.io.RandomAccessFile
import java.util.UUID
import kotlin.math.*

data class PhotoQuality(val accepted: Boolean, val reason: String, val sharpness: Double, val meanLight: Double)
data class CapturedPage(val id: String, val file: File, val thumbnail: File, val width: Int, val height: Int)

/** Fast screening only; this is not a promise that every printed character is legible. */
object PhotoChecks {
    fun assess(bitmap: Bitmap): PhotoQuality {
        if (max(bitmap.width, bitmap.height) < 1400 || min(bitmap.width, bitmap.height) < 800)
            return PhotoQuality(false, "Move closer and retake the whole page at a higher resolution.", 0.0, 0.0)
        val scale = min(1.0, 900.0 / max(bitmap.width, bitmap.height))
        val small = Bitmap.createScaledBitmap(bitmap, (bitmap.width * scale).roundToInt(), (bitmap.height * scale).roundToInt(), true)
        try {
            val w = small.width; val h = small.height
            val pixels = IntArray(w * h); small.getPixels(pixels, 0, w, 0, 0, w, h)
            val gray = IntArray(pixels.size) { i -> val p = pixels[i]; (((p shr 16) and 255) * 77 + ((p shr 8) and 255) * 150 + (p and 255) * 29) shr 8 }
            var light = 0.0; var sum = 0.0; var squared = 0.0; var edges = 0; var count = 0
            // Exclude the outer margin so a sharp table edge/background does not
            // wholly dominate blur screening. Never change the source image.
            for (y in max(1, h / 20) until min(h - 1, h * 19 / 20)) for (x in max(1, w / 20) until min(w - 1, w * 19 / 20)) {
                val i = y * w + x; val lap = gray[i - 1] + gray[i + 1] + gray[i - w] + gray[i + w] - 4 * gray[i]
                light += gray[i]; sum += lap; squared += lap.toDouble() * lap; if (abs(lap) > 24) edges++; count++
            }
            val mean = light / count; val variance = max(0.0, squared / count - (sum / count).pow(2))
            val reason = when {
                mean < 55 -> "The page is too dark. Add even light and retake it."
                variance < 45 || edges.toDouble() / count < .002 -> "The text looks blurred, blank or washed out. Hold steady, fill the frame and retake it."
                else -> "Check that every edge and line is visible before submitting."
            }
            return PhotoQuality(mean >= 55 && variance >= 45 && edges.toDouble() / count >= .002, reason, variance, mean)
        } finally { if (small !== bitmap) small.recycle() }
    }
}

object CaptureDocuments {
    const val MAX_PAGES = 12
    const val MAX_BYTES = 10 * 1024 * 1024

    /** Decode one bounded bitmap, apply all EXIF rotations/reflections, and strip metadata. */
    fun decode(file: File, maxEdge: Int = 2600): Bitmap {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.path, bounds)
        require(bounds.outWidth > 0 && bounds.outHeight > 0 && bounds.outWidth.toLong() * bounds.outHeight <= 30_000_000) { "Use a photo smaller than 30 megapixels." }
        var sample = 1
        while (max(bounds.outWidth, bounds.outHeight) / (sample * 2) >= maxEdge) sample *= 2
        var bitmap = BitmapFactory.decodeFile(file.path, BitmapFactory.Options().apply { inSampleSize = sample }) ?: error("The photo could not be opened. Retake it.")
        val matrix = Matrix()
        when (runCatching { ExifInterface(file).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL) }.getOrDefault(1)) {
            2 -> matrix.setScale(-1f, 1f)
            3 -> matrix.setRotate(180f)
            4 -> { matrix.setRotate(180f); matrix.postScale(-1f, 1f) }
            5 -> { matrix.setRotate(90f); matrix.postScale(-1f, 1f) }
            6 -> matrix.setRotate(90f)
            7 -> { matrix.setRotate(-90f); matrix.postScale(-1f, 1f) }
            8 -> matrix.setRotate(-90f)
        }
        if (!matrix.isIdentity) { val oriented = Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true); if (oriented !== bitmap) bitmap.recycle(); bitmap = oriented }
        if (max(bitmap.width, bitmap.height) > maxEdge) {
            val ratio = maxEdge.toFloat() / max(bitmap.width, bitmap.height)
            val scaled = Bitmap.createScaledBitmap(bitmap, (bitmap.width * ratio).roundToInt(), (bitmap.height * ratio).roundToInt(), true)
            if (scaled !== bitmap) bitmap.recycle(); bitmap = scaled
        }
        return bitmap
    }

    fun prepare(file: File): Pair<CapturedPage?, PhotoQuality> {
        val bitmap = decode(file)
        try {
            val quality = PhotoChecks.assess(bitmap)
            if (!quality.accepted) return null to quality
            val temp = File(file.parentFile, "${UUID.randomUUID()}.normalized")
            try { temp.outputStream().use { check(bitmap.compress(Bitmap.CompressFormat.JPEG, 90, it)) }; check(temp.renameTo(file)) { "Could not save this page. Retry capture." } }
            finally { temp.delete() }
            val thumb = File(file.parentFile, "${file.nameWithoutExtension}.thumb.jpg")
            val scale = 200f / max(bitmap.width, bitmap.height)
            val thumbnail = Bitmap.createScaledBitmap(bitmap, (bitmap.width * scale).roundToInt(), (bitmap.height * scale).roundToInt(), true)
            try { thumb.outputStream().use { thumbnail.compress(Bitmap.CompressFormat.JPEG, 80, it) } } finally { if (thumbnail !== bitmap) thumbnail.recycle() }
            return CapturedPage(file.nameWithoutExtension, file, thumb, bitmap.width, bitmap.height) to quality
        } finally { bitmap.recycle() }
    }

    /** Embed the already compressed JPEGs without rasterizing/recompressing a whole PDF. */
    fun writePdf(pages: List<CapturedPage>, target: File): File {
        require(pages.size in 1..MAX_PAGES) { "Capture between 1 and 12 pages." }
        require(pages.sumOf { it.file.length() } + 20000 < MAX_BYTES) { "This document exceeds 10 MB. Remove pages or split it into smaller notices; your photos are still available." }
        val count = 2 + pages.size * 3
        val offsets = LongArray(count + 1)
        try {
            RandomAccessFile(target, "rw").use { out ->
                out.setLength(0); out.writeBytes("%PDF-1.4\n%Docket captured document\n")
                fun obj(id: Int, body: String) { offsets[id] = out.filePointer; out.writeBytes("$id 0 obj\n$body\nendobj\n") }
                obj(1, "<< /Type /Catalog /Pages 2 0 R >>")
                obj(2, "<< /Type /Pages /Count ${pages.size} /Kids [${pages.indices.joinToString(" ") { "${3 + it * 3} 0 R" }}] >>")
                pages.forEachIndexed { index, page ->
                    require(page.file.isFile) { "A captured page is no longer available. Retake it." }
                    val id = 3 + index * 3
                    val width = 595; val height = (width.toDouble() * page.height / page.width).roundToInt().coerceAtLeast(1)
                    obj(id, "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 $width $height] /Resources << /XObject << /Photo ${id + 1} 0 R >> >> /Contents ${id + 2} 0 R >>")
                    offsets[id + 1] = out.filePointer
                    out.writeBytes("${id + 1} 0 obj\n<< /Type /XObject /Subtype /Image /Width ${page.width} /Height ${page.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${page.file.length()} >>\nstream\n")
                    page.file.inputStream().use { input -> val buffer = ByteArray(16384); while (true) { val n = input.read(buffer); if (n < 0) break; out.write(buffer, 0, n) } }
                    out.writeBytes("\nendstream\nendobj\n")
                    val command = "q $width 0 0 $height 0 0 cm /Photo Do Q\n"
                    obj(id + 2, "<< /Length ${command.toByteArray(Charsets.US_ASCII).size} >>\nstream\n${command}endstream")
                }
                val xref = out.filePointer
                out.writeBytes("xref\n0 ${count + 1}\n0000000000 65535 f \n")
                (1..count).forEach { out.writeBytes(String.format(java.util.Locale.US, "%010d 00000 n \n", offsets[it])) }
                out.writeBytes("trailer\n<< /Size ${count + 1} /Root 1 0 R >>\nstartxref\n$xref\n%%EOF\n")
                require(out.length() <= MAX_BYTES) { "The document exceeds 10 MB. Split it into smaller notices." }
            }
            return target
        } catch (e: Exception) { target.delete(); throw e }
    }
}
