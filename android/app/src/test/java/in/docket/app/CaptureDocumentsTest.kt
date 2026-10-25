package `in`.docket.app

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.media.ExifInterface
import android.app.Application
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class CaptureDocumentsTest {
    private fun page(label: String, color: Int = Color.BLACK): Bitmap {
        val bitmap = Bitmap.createBitmap(1800, 2500, Bitmap.Config.ARGB_8888)
        bitmap.eraseColor(Color.WHITE)
        val canvas = Canvas(bitmap)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { textSize = 46f; this.color = color }
        canvas.drawText(label, 120f, 140f, paint)
        paint.color = Color.BLACK
        listOf("FICTIONAL CAMERA TEST - NOT A LEGAL NOTICE", "Date: 15/10/2026", "Please respond within 15 days of receipt.", "GST notice for document capture and source review.", "धारा ७३ के अंतर्गत अपना स्पष्टीकरण प्रस्तुत करें।").forEachIndexed { i, line -> canvas.drawText(line, 120f, 260f + i * 90, paint) }
        for (i in 0..13) canvas.drawText("Source record ${i + 1}: check the original before acting.", 120f, 900f + i * 78, paint)
        return bitmap
    }
    private fun saved(label: String): CapturedPage {
        val folder = File(RuntimeEnvironment.getApplication().cacheDir, "camera-tests").apply { mkdirs() }
        val file = File(folder, "${java.util.UUID.randomUUID()}.jpg")
        val bitmap = page(label)
        file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.JPEG, 92, it) }; bitmap.recycle()
        val (prepared, result) = CaptureDocuments.prepare(file)
        assertTrue(result.reason + " sharpness=${result.sharpness}", result.accepted)
        return prepared!!
    }
    @Test fun fastChecksRejectBlankDarkTinyAndSevereBlurButAcceptPrintedPage() {
        val printed = page("PAGE ONE")
        assertTrue(PhotoChecks.assess(printed).accepted)
        val blank = Bitmap.createBitmap(1800,2500,Bitmap.Config.ARGB_8888).apply { eraseColor(Color.WHITE) }
        assertFalse(PhotoChecks.assess(blank).accepted)
        blank.eraseColor(Color.rgb(20,20,20)); assertFalse(PhotoChecks.assess(blank).accepted)
        val tiny = Bitmap.createScaledBitmap(printed,360,500,true); assertFalse(PhotoChecks.assess(tiny).accepted)
        val reduced = Bitmap.createScaledBitmap(printed,36,50,true)
        val blurred = Bitmap.createScaledBitmap(reduced,1800,2500,true)
        assertFalse(PhotoChecks.assess(blurred).accepted)
        listOf(printed,blank,tiny,reduced,blurred).forEach(Bitmap::recycle)
    }
    @Test fun pdfEmbedsEveryJpegInChosenOrderAndRejectsOverLimit() {
        val first = saved("PAGE ONE"); val second = saved("PAGE TWO")
        val destination = File("build/native-previews/camera-two-pages.pdf").apply { parentFile!!.mkdirs() }
        CaptureDocuments.writePdf(listOf(second,first),destination)
        val body = destination.readBytes().toString(Charsets.ISO_8859_1)
        assertTrue(body.startsWith("%PDF-1.4")); assertTrue(body.contains("/Count 2")); assertTrue(body.contains("/Kids [3 0 R 6 0 R]"))
        val bytes = destination.readBytes(); val secondJpeg = second.file.readBytes(); val firstJpeg = first.file.readBytes()
        fun indexOf(needle: ByteArray) = bytes.indices.first { index -> index + needle.size <= bytes.size && needle.indices.all { bytes[index + it] == needle[it] } }
        assertTrue(indexOf(secondJpeg)<indexOf(firstJpeg))
        assertThrows(IllegalArgumentException::class.java) { CaptureDocuments.writePdf(List(13) { first },File(destination.parentFile,"too-many.pdf")) }
        val giant = File(first.file.parentFile,"huge.jpg").apply { java.io.RandomAccessFile(this,"rw").use { it.setLength(CaptureDocuments.MAX_BYTES.toLong()) } }
        assertThrows(IllegalArgumentException::class.java) { CaptureDocuments.writePdf(listOf(first.copy(file=giant)),File(destination.parentFile,"too-large.pdf")) }
        giant.delete()
    }
    @Test fun cameraPreparationAppliesExifRotationAndRemovesGpsMetadata() {
        val source = saved("ORIENTATION")
        val exif = ExifInterface(source.file)
        exif.setAttribute(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_ROTATE_90.toString())
        exif.setAttribute(ExifInterface.TAG_GPS_LATITUDE, "12/1,30/1,0/1");exif.saveAttributes()
        val bitmap = CaptureDocuments.decode(source.file)
        assertEquals(source.height,bitmap.width);assertEquals(source.width,bitmap.height);bitmap.recycle()
        val prepared = CaptureDocuments.prepare(source.file).first!!
        assertNull(ExifInterface(prepared.file).getAttribute(ExifInterface.TAG_GPS_LATITUDE))
        assertTrue(ExifInterface(prepared.file).getAttributeInt(ExifInterface.TAG_ORIENTATION,1) in listOf(ExifInterface.ORIENTATION_UNDEFINED,ExifInterface.ORIENTATION_NORMAL))
    }
    @Test fun automaticLanguageRecognitionKeepsMixedScriptsAndUnknowns() {
        assertEquals(listOf("en"),OcrChecks.detectedLanguages("English notice"))
        assertEquals(listOf("hi"),OcrChecks.detectedLanguages("कार्यालय का नोटिस"))
        assertEquals(listOf("en","hi"),OcrChecks.detectedLanguages("GST धारा ७३"))
        assertTrue(OcrChecks.detectedLanguages("123456").isEmpty())
    }
}
