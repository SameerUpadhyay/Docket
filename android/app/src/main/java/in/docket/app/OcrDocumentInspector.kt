package `in`.docket.app

import android.graphics.BitmapFactory
import android.graphics.pdf.PdfRenderer
import android.os.ParcelFileDescriptor
import android.net.Uri
import android.graphics.Bitmap
import android.graphics.Color as AndroidColor
import androidx.compose.foundation.Image
import androidx.compose.foundation.relocation.BringIntoViewRequester
import androidx.compose.foundation.relocation.bringIntoViewRequester
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.Canvas as DrawCanvas
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.platform.LocalContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun OcrDocumentInspector(notice: Notice, vm: DocketViewModel, modal: Boolean = true, close: () -> Unit) {
    val analysis = notice.json.optJSONObject("ocr_analysis")
    val structured = analysis?.optJSONObject("structured_triage")
    val quality = notice.json.optJSONObject("ocr_report")
    val highlights = structured?.optJSONArray("key_highlights")?.objects().orEmpty()
    val sourceRequest = remember { BringIntoViewRequester() }
    var sourceSize by remember { mutableStateOf(IntSize.Zero) }
    var page by remember { mutableIntStateOf(1) }
    var selected by remember { mutableIntStateOf(-1) }
    var hindi by remember { mutableStateOf(false) }
    var bitmap by remember { mutableStateOf<Bitmap?>(null) }
    var sourceMessage by remember { mutableStateOf("") }
    val context = LocalContext.current
    val pageCount = analysis?.optInt("page_count") ?: quality?.optInt("page_count", 1) ?: 1
    LaunchedEffect(page) {
        sourceMessage = "Opening source page…"; bitmap = null
        try {
            bitmap = withContext(Dispatchers.IO) {
                if (vm.store.connected) {
                    val bytes = vm.api().download("/notices/${notice.id}/ocr/pages/$page.png")
                    BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: error("Source image could not be opened.")
                } else {
                    val captured = notice.json.optBoolean("source_capture")
                    val uri = notice.json.text("source_uri").takeIf { it.isNotBlank() }?.let(Uri::parse)
                    if (!captured && uri == null) error("Source is not retained. Keep your original document for comparison.")
                    if (notice.json.text("original_filename").endsWith(".pdf", true)) {
                        val temp = File.createTempFile("ocr-preview-", ".pdf", context.cacheDir)
                        try {
                            if (captured) temp.writeBytes(vm.store.cameraOriginal(notice.id)) else context.contentResolver.openInputStream(uri!!)!!.use { input -> temp.outputStream().use { input.copyTo(it) } }
                            ParcelFileDescriptor.open(temp, ParcelFileDescriptor.MODE_READ_ONLY).use { descriptor -> PdfRenderer(descriptor).use { renderer -> renderer.openPage(page - 1).use { source ->
                                val scale = minOf(1600f/source.width, 2200f/source.height)
                                Bitmap.createBitmap((source.width*scale).toInt(), (source.height*scale).toInt(), Bitmap.Config.ARGB_8888).also { it.eraseColor(AndroidColor.WHITE); source.render(it, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY) }
                            } } }
                        } finally { temp.delete() }
                    } else context.contentResolver.openInputStream(uri!!)?.use(BitmapFactory::decodeStream) ?: error("The source is no longer available.")
                }
            }
            sourceMessage = "Source coordinates are candidates; compare the highlighted area with the printed notice."
        } catch (e: Exception) { sourceMessage = e.message.orEmpty() }
    }
    LaunchedEffect(selected, bitmap) {
        val box = highlights.getOrNull(selected)?.optJSONArray("box_2d")
        if (box != null && bitmap != null && sourceSize.width > 0) sourceRequest.bringIntoView(Rect(box.optInt(1)/1000f*sourceSize.width, box.optInt(0)/1000f*sourceSize.height, box.optInt(3)/1000f*sourceSize.width, box.optInt(2)/1000f*sourceSize.height))
    }
    val content: @Composable () -> Unit = {
        Scaffold(topBar = { TopAppBar(title = { Text("Inspect document") }, navigationIcon = { TextButton(onClick = close) { Text("Back") } }) }, containerColor = Canvas) { padding ->
            Column(Modifier.padding(padding).fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                Text("English + हिन्दी · source review", style = MaterialTheme.typography.titleLarge)
                Text("${quality?.optInt("page_count", 1) ?: pageCount} page(s) · ${((quality?.optInt("elapsed_ms") ?: analysis?.optInt("processing_latency_ms") ?: 0)/1000.0)} seconds", style = MaterialTheme.typography.bodySmall, color = Muted)
                val math = if (analysis?.isNull("table_math_verified") != false) "Table arithmetic not verified" else if (analysis.optBoolean("table_math_verified")) "Printed totals agree arithmetically" else "Table totals disagree · check the source"
                InfoBanner(math, analysis?.text("table_math_discrepancy_note", "No reconstructable table was found. Recognition confidence is not legal or factual accuracy.") ?: "Review dates, amounts, references and all Hindi/English text against the source.")
                if (pageCount > 1) Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    TextButton(onClick = { page--; selected = -1 }, enabled = page > 1) { Text("Previous") }
                    Text("Page $page of $pageCount", modifier = Modifier.padding(top = 12.dp))
                    TextButton(onClick = { page++; selected = -1 }, enabled = page < pageCount) { Text("Next") }
                }
                bitmap?.let { source ->
                    Box(Modifier.fillMaxWidth().aspectRatio(source.width.toFloat()/source.height).bringIntoViewRequester(sourceRequest).onSizeChanged { sourceSize = it }) {
                        Image(source.asImageBitmap(), "Original notice page $page", modifier = Modifier.fillMaxSize())
                        val chosen = highlights.getOrNull(selected)?.takeIf { it.optInt("page_number") == page }?.optJSONArray("box_2d")
                        if (chosen != null && chosen.length() == 4) DrawCanvas(Modifier.fillMaxSize()) {
                            val top=chosen.optInt(0)/1000f*size.height; val left=chosen.optInt(1)/1000f*size.width
                            val width=(chosen.optInt(3)-chosen.optInt(1))/1000f*size.width; val height=(chosen.optInt(2)-chosen.optInt(0))/1000f*size.height
                            drawRect(Gold.copy(alpha=.22f),Offset(left,top),Size(width,height)); drawRect(Navy,Offset(left,top),Size(width,height),style=Stroke(2.dp.toPx()))
                        }
                    }
                }
                Text(sourceMessage, style = MaterialTheme.typography.bodySmall, color = Muted)
                if (highlights.isNotEmpty()) SurfaceCard {
                    Text("Locate a field", style = MaterialTheme.typography.titleMedium)
                    highlights.forEachIndexed { index, field ->
                        FilterChip(selected == index, { selected = index; page = field.optInt("page_number",1) }, label = { Text("${field.text("label")}: ${field.text("extracted_value")}") })
                        if (selected == index && field.text("provenance") == "model-estimate") Text("This location was suggested by the model; verify its alignment.", style = MaterialTheme.typography.bodySmall, color = GoldInk)
                    }
                }
                SurfaceCard {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) { Text("What was read", style = MaterialTheme.typography.titleMedium); TextButton(onClick = { hindi = !hindi }) { Text(if (hindi) "English" else "हिन्दी") } }
                    Text(structured?.text(if (hindi) "core_allegation_hindi" else "core_allegation_english") ?: notice.summary, style = MaterialTheme.typography.bodyLarge.copy(lineHeight = if (hindi) 28.sp else 24.sp))
                    structured?.text("response_window_days").takeUnless { it.isNullOrBlank() }?.let { Text("Printed period candidate: $it days. Confirm service and applicability.", style = MaterialTheme.typography.bodySmall) }
                }
                val rows = structured?.optJSONArray("tax_breakdown_table")?.objects().orEmpty()
                if (rows.isNotEmpty()) SurfaceCard {
                    Text("Reconstructed demand table", style = MaterialTheme.typography.titleMedium)
                    rows.forEach { row ->
                        Text(row.text("tax_head"), style = MaterialTheme.typography.titleSmall)
                        listOf("tax_or_principal_inr" to "Principal / tax", "interest_inr" to "Interest", "penalty_inr" to "Penalty", "late_fee_inr" to "Late fee", "row_total_inr" to "Printed row total").forEach { (key,label) -> DetailLine(label, if (row.isNull(key)) "Not established" else "INR ${row.text(key)}") }
                        HorizontalDivider()
                    }
                }
                val warnings = analysis?.optJSONArray("warnings")?.strings().orEmpty()
                warnings.forEach { Text(it, style = MaterialTheme.typography.bodySmall, color = GoldInk) }
                SurfaceCard { Text("Redacted transcript", style = MaterialTheme.typography.titleMedium); Text(structured?.text("full_markdown_transcript") ?: notice.redactedText, style = MaterialTheme.typography.bodyMedium) }
            }
        }
    }
    if (modal) Dialog(onDismissRequest = close, properties = DialogProperties(usePlatformDefaultWidth = false)) { content() } else content()
}
