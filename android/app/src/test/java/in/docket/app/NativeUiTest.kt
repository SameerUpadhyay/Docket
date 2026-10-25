package `in`.docket.app

import android.graphics.Bitmap
import android.graphics.Canvas
import androidx.activity.compose.setContent
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.material3.Text
import androidx.lifecycle.ViewModelProvider
import org.json.JSONObject
import android.net.Uri
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

/** Runs the actual Compose activity in an isolated Android runtime, not a web mock-up. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], qualifiers = "w412dp-h892dp-mdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class NativeUiTest {
    @get:Rule val compose = createAndroidComposeRule<MainActivity>()
    private fun snapshot(name: String, dialog: Boolean = false) {
        compose.waitForIdle()
        // Draw the real Android view tree. PixelCopy/captureToImage relies on a
        // hardware compositor that does not exist in this headless runtime.
        compose.runOnIdle {
            val view = if (dialog) org.robolectric.shadows.ShadowDialog.getLatestDialog().window!!.decorView else compose.activity.window.decorView
            val bitmap = Bitmap.createBitmap(view.width, view.height, Bitmap.Config.ARGB_8888)
            view.draw(Canvas(bitmap))
            val destination = File("build/native-previews/$name.png").apply { parentFile!!.mkdirs() }
            destination.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
            bitmap.recycle()
        }
    }
    @Test fun addNoticeKeepsFileUploadAndCameraWithoutTextOrLanguagePrompts() {
        compose.onNodeWithText("Explore sample workspace").performClick()
        compose.mainClock.advanceTimeBy(1000)
        compose.onNodeWithText("Add notice", useUnmergedTree = true).performClick()
        compose.onNodeWithText("Capture pages").assertIsDisplayed()
        compose.onNodeWithText("Choose file").assertIsDisplayed()
        compose.onNodeWithText("Paste text").assertDoesNotExist()
        compose.onNodeWithText("Document language").assertDoesNotExist()
        snapshot("add-notice-camera")
        compose.onNodeWithText("Capture pages").performClick()
        compose.onNodeWithText("Allow camera").assertIsDisplayed()
        compose.onNodeWithText("Submit 0 pages").assertIsNotEnabled()
        snapshot("camera-permission")
        compose.onNodeWithText("Back", substring = false).performClick()
        compose.onNodeWithText("Choose file").assertIsDisplayed()
    }
    @Test fun capturedPagesRetakeReorderAndSubmitAsOnePdf() {
        lateinit var camera: CaptureViewModel
        compose.runOnUiThread {
            camera = ViewModelProvider(compose.activity)[CaptureViewModel::class.java]
            compose.activity.setContent { DocketTheme { androidx.compose.foundation.layout.Column {
                val state by camera.state.collectAsState()
                Text("Camera page review")
                CapturePageStrip(state, camera::retake, camera::remove, camera::move)
            } } }
        }
        fun capture(blank: Boolean = false) {
            compose.runOnUiThread {
                val destination = camera.newPhoto()!!
                val source = if (blank) Bitmap.createBitmap(1800,2500,Bitmap.Config.ARGB_8888).apply { eraseColor(android.graphics.Color.WHITE) } else {
                    val original = javaClass.classLoader!!.getResourceAsStream("ocr/source.png")!!.use(android.graphics.BitmapFactory::decodeStream)
                    Bitmap.createScaledBitmap(original,1800,2546,true).also { original.recycle() }
                }
                destination.outputStream().use { source.compress(Bitmap.CompressFormat.JPEG,92,it) };source.recycle()
                camera.captured(destination)
            }
            compose.waitUntil(15000) { org.robolectric.Shadows.shadowOf(android.os.Looper.getMainLooper()).idle(); !camera.state.value.busy }
        }
        capture();capture(blank = true)
        compose.runOnUiThread { camera.dismissRetake() }
        org.junit.Assert.assertTrue(camera.state.value.awaitingRetake)
        var skippedUnreadablePage = false
        compose.runOnUiThread { camera.submit { skippedUnreadablePage = true } }
        org.junit.Assert.assertFalse(camera.state.value.busy)
        org.junit.Assert.assertFalse(skippedUnreadablePage)
        capture()
        org.junit.Assert.assertEquals(2,camera.state.value.pages.size)
        val original = camera.state.value.pages.first()
        compose.onNodeWithText("Page 1", substring = false).performClick()
        compose.onNodeWithText("Review page 1").performClick()
        compose.waitUntil(10000) { compose.onAllNodesWithContentDescription("Full captured page").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("Zoom in").performClick()
        snapshot("camera-page-review", dialog = true)
        compose.onNodeWithText("Done").performClick()
        compose.onNodeWithText("Retake 1").performClick()
        capture(blank = true)
        org.junit.Assert.assertNotNull(camera.state.value.rejected)
        org.junit.Assert.assertEquals(original.id,camera.state.value.pages.first().id)
        org.junit.Assert.assertTrue(original.file.exists())
        compose.runOnUiThread { camera.dismissRetake() }
        capture()
        org.junit.Assert.assertEquals(2,camera.state.value.pages.size)
        org.junit.Assert.assertNotEquals(original.id,camera.state.value.pages.first().id)
        org.junit.Assert.assertFalse(original.file.exists())
        val replacement = camera.state.value.pages.first().id
        compose.onNodeWithContentDescription("Move page later").performClick()
        org.junit.Assert.assertEquals(replacement,camera.state.value.pages.last().id)
        snapshot("camera-page-queue")
        var document: File? = null
        compose.runOnUiThread { camera.submit { document = it } }
        compose.waitUntil(10000) { org.robolectric.Shadows.shadowOf(android.os.Looper.getMainLooper()).idle(); document != null && !camera.state.value.busy }
        val store = NoticeStore(compose.activity)
        org.junit.Assert.assertTrue(store.selectedFile(Uri.fromFile(document!!)).first.endsWith(".pdf"))
        compose.runOnUiThread { camera.clear() }
        org.junit.Assert.assertTrue(document!!.exists())
        org.junit.Assert.assertTrue(store.isCameraDocument(Uri.fromFile(document!!)))
        store.discardCameraDocument(Uri.fromFile(document!!))
        org.junit.Assert.assertFalse(document!!.exists())
    }
    @Test fun bilingualInspectorRendersSourceFieldsAndPrintedTable() {
        val analysis = javaClass.classLoader!!.getResourceAsStream("ocr/analysis.json")!!.bufferedReader().use { JSONObject(it.readText()) }
        val source = File(compose.activity.cacheDir, "fictional-ocr-source.png")
        javaClass.classLoader!!.getResourceAsStream("ocr/source.png")!!.use { input -> source.outputStream().use { input.copyTo(it) } }
        val notice = Notice(JSONObject().put("id", "synthetic-ocr-ui").put("source_uri", Uri.fromFile(source).toString()).put("original_filename", "fictional.png").put("ocr_analysis", analysis).put("ocr_report", JSONObject().put("page_count", 1).put("elapsed_ms", 4000)))
        compose.runOnUiThread {
            val model = ViewModelProvider(compose.activity)[DocketViewModel::class.java]
            compose.activity.setContent { DocketTheme { OcrDocumentInspector(notice, model, modal = false, close = {}) } }
        }
        compose.waitUntil(10000) { compose.onAllNodesWithContentDescription("Original notice page 1").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("Inspect document").assertIsDisplayed()
        compose.onNodeWithText("Printed totals agree arithmetically").assertExists()
        snapshot("ocr-source")
        compose.onNodeWithText("Reconstructed demand table").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("CGST", substring = false).performScrollTo().assertIsDisplayed()
        compose.onAllNodesWithText("INR 80000.00").onFirst().performScrollTo().assertIsDisplayed()
        snapshot("ocr-table")
    }
    @Test fun accountEntryAndRecoveryNavigation() {
        compose.onNodeWithText("Your business. In order.").assertIsDisplayed()
        snapshot("login")
        compose.onNodeWithText("Create account", substring = false).performClick()
        compose.onNodeWithText("Create your business account").assertIsDisplayed()
        compose.onNodeWithText("Business name").assertIsDisplayed()
        snapshot("registration")
        compose.onNodeWithText("Back to sign in").performClick()
        compose.onNodeWithText("Forgot password?").performClick()
        compose.onNodeWithText("Recover your account").assertIsDisplayed()
        compose.onNodeWithText("Send recovery code").assertIsDisplayed()
    }
    @Test fun navigationAndCaseWorkflow() {
        compose.onNodeWithText("Explore sample workspace").performClick()
        compose.onNodeWithText("A clearer way forward.").assertIsDisplayed()
        snapshot("home")
        compose.onNodeWithText("Notices", substring = false).performClick()
        compose.onNodeWithText("Your notices").assertIsDisplayed()
        compose.onNodeWithTag("service-Tax").performClick()
        compose.onNodeWithText("Input tax credit mismatch").assertIsDisplayed()
        snapshot("notices")
        compose.onNodeWithText("Input tax credit mismatch").performClick()
        compose.onNodeWithText("Response", substring = false).performClick()
        compose.onNodeWithText("Build your response").assertIsDisplayed()
        snapshot("response")
        compose.onNodeWithContentDescription("Back", substring = false).performClick()
        compose.onNodeWithText("Deadlines", substring = false).performClick()
        compose.onNodeWithText("Stay ahead of deadlines").assertIsDisplayed()
        snapshot("deadlines")
        compose.onNodeWithText("Workspace", substring = false).performClick()
        compose.onNodeWithText("Your workspace").assertIsDisplayed()
        snapshot("workspace")
    }
    @Test fun quarantineHasNoReplyWorkflow() {
        compose.onNodeWithText("Explore sample workspace").performClick()
        compose.onNodeWithText("Notices", substring = false).performClick()
        compose.onNodeWithTag("service-Security").performClick()
        compose.onNodeWithText("Suspicious payment notice").performClick()
        compose.onNodeWithText("Review the warning signs").assertIsDisplayed()
        compose.onNodeWithText("Response", substring = false).assertDoesNotExist()
        snapshot("quarantine")
    }
}
