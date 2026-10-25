package `in`.docket.app

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Size
import android.view.MotionEvent
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.*
import androidx.camera.core.resolutionselector.*
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.geometry.Offset
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.util.concurrent.Executors

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun CameraCaptureScreen(model: CaptureViewModel, close: () -> Unit, ready: (File) -> Unit) {
    val state by model.state.collectAsState()
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current
    var permission by remember { mutableStateOf(ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) }
    val request = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { permission = it }
    var capture by remember { mutableStateOf<ImageCapture?>(null) }
    var camera by remember { mutableStateOf<Camera?>(null) }
    var light by remember { mutableStateOf(false) }
    var cameraError by remember { mutableStateOf("") }
    var discard by remember { mutableStateOf(false) }
    val executor = remember { Executors.newSingleThreadExecutor() }
    DisposableEffect(Unit) { onDispose { executor.shutdown() } }
    DisposableEffect(lifecycle) {
        val observer = LifecycleEventObserver { _, event -> if (event == Lifecycle.Event.ON_RESUME) permission = ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED }
        lifecycle.lifecycle.addObserver(observer); onDispose { lifecycle.lifecycle.removeObserver(observer) }
    }
    fun back() { if (!state.busy) { if (state.pages.isEmpty()) close() else discard = true } }
    BackHandler { back() }
    Scaffold(containerColor = Canvas, topBar = { TopAppBar(title = { Text("Scan notice") }, navigationIcon = { TextButton(onClick = ::back, enabled = !state.busy) { Text("Back") } }) }, bottomBar = {
        Surface(color = Canvas) { Column(Modifier.navigationBarsPadding().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (state.retake != null) TextButton(onClick = model::cancelRetake, enabled = !state.busy) { Text("Keep previous page") }
            if (state.awaitingRetake && state.retake == null) TextButton(onClick = model::skipFailedPhoto, enabled = !state.busy) { Text("Discard failed photo") }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedButton(onClick = {
                    val shot = capture ?: return@OutlinedButton
                    val file = model.newPhoto() ?: return@OutlinedButton
                    try {
                    shot.targetRotation = (context as? android.app.Activity)?.windowManager?.defaultDisplay?.rotation ?: android.view.Surface.ROTATION_0
                    shot.takePicture(ImageCapture.OutputFileOptions.Builder(file).build(), executor, object : ImageCapture.OnImageSavedCallback {
                        override fun onImageSaved(result: ImageCapture.OutputFileResults) { ContextCompat.getMainExecutor(context).execute { model.captured(file) } }
                        override fun onError(exception: ImageCaptureException) { ContextCompat.getMainExecutor(context).execute { model.failed(file, "Could not capture. Hold steady and try again.") } }
                    })
                    } catch (_: Exception) { model.failed(file, "Camera paused. Reopen it or choose an existing file.") }
                }, enabled = permission && capture != null && cameraError.isEmpty() && !state.busy && state.rejected == null && (state.pages.size < CaptureDocuments.MAX_PAGES || state.retake != null), modifier = Modifier.weight(1f)) {
                    Icon(Icons.Outlined.PhotoCamera, null, Modifier.size(20.dp)); Spacer(Modifier.width(6.dp)); Text(if (state.retake != null || state.awaitingRetake) "Retake page" else "Capture page")
                }
                Button(onClick = { model.submit(ready) }, enabled = state.pages.isNotEmpty() && !state.busy && state.retake == null && state.rejected == null && !state.awaitingRetake, modifier = Modifier.weight(1f)) { Text("Submit ${state.pages.size} ${if (state.pages.size == 1) "page" else "pages"}") }
            }
            Text("Submit combines all pages into one document for recognition.", style = MaterialTheme.typography.bodySmall, color = Muted)
        } }
    }) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(if (state.retake != null) "Replace page ${state.retake!! + 1}" else if (state.pages.size >= CaptureDocuments.MAX_PAGES) "12 pages captured · document limit" else "Capture page ${state.pages.size + 1} · up to 12 pages", style = MaterialTheme.typography.titleMedium)
            Text("Keep all four edges visible. Tap the page to focus; avoid shadows and glare.", style = MaterialTheme.typography.bodySmall, color = Muted)
            Box(Modifier.fillMaxWidth().weight(1f).background(androidx.compose.ui.graphics.Color.Black, RoundedCornerShape(12.dp)), contentAlignment = Alignment.Center) {
                if (permission) CameraPreview(onReady = { imageCapture, boundCamera -> capture = imageCapture; camera = boundCamera; cameraError = "" }, onError = { capture = null; cameraError = it })
                else Column(Modifier.padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("Camera access is needed to photograph pages.", color = androidx.compose.ui.graphics.Color.White)
                    Button(onClick = { request.launch(Manifest.permission.CAMERA) }) { Text("Allow camera") }
                    Text("You can also go back and choose an existing file. If access is blocked, enable Camera in Android app settings.", style = MaterialTheme.typography.bodySmall, color = androidx.compose.ui.graphics.Color.White)
                }
                if (cameraError.isNotBlank()) Text(cameraError, color = androidx.compose.ui.graphics.Color.White, modifier = Modifier.padding(20.dp))
                if (state.busy) CircularProgressIndicator(color = Gold, modifier = Modifier.align(Alignment.Center))
                if (permission && camera?.cameraInfo?.hasFlashUnit() == true) TextButton(onClick = { light = !light; camera?.cameraControl?.enableTorch(light) }, modifier = Modifier.align(Alignment.TopEnd)) { Text(if (light) "Light off" else "Light on", color = androidx.compose.ui.graphics.Color.White) }
            }
            Text(state.message.ifBlank { "Quick photo checks run on this device. OCR runs after you submit." }, style = MaterialTheme.typography.bodySmall, color = Navy)
            CapturePageStrip(state, model::retake, model::remove, model::move)
        }
    }
    state.rejected?.let { quality -> AlertDialog(onDismissRequest = model::dismissRetake, title = { Text("Retake this page") }, text = { Text(quality.reason + " Your other pages are kept.") }, confirmButton = { TextButton(onClick = model::dismissRetake) { Text("Retake photo") } }) }
    if (discard) AlertDialog(onDismissRequest = { discard = false }, title = { Text("Discard captured pages?") }, text = { Text("This removes the camera draft. A document already attached to the notice is kept.") }, confirmButton = { TextButton(onClick = { model.clear(); close() }) { Text("Discard photos") } }, dismissButton = { TextButton(onClick = { discard = false }) { Text("Keep capturing") } })
}

@Composable private fun CameraPreview(onReady: (ImageCapture, Camera) -> Unit, onError: (String) -> Unit) {
    val context = LocalContext.current; val lifecycle = LocalLifecycleOwner.current
    val view = remember { PreviewView(context).apply { implementationMode = PreviewView.ImplementationMode.COMPATIBLE; scaleType = PreviewView.ScaleType.FIT_CENTER } }
    val latestReady by rememberUpdatedState(onReady); val latestError by rememberUpdatedState(onError)
    DisposableEffect(lifecycle, view) {
        val future = ProcessCameraProvider.getInstance(context)
        var disposed = false; var provider: ProcessCameraProvider? = null
        val preview = Preview.Builder().build().also { it.setSurfaceProvider(view.surfaceProvider) }
        val image = ImageCapture.Builder().setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY).setJpegQuality(92).setResolutionSelector(ResolutionSelector.Builder().setResolutionStrategy(ResolutionStrategy(Size(2400, 3200), ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER)).build()).build()
        future.addListener({ if (!disposed) try {
            provider = future.get()
            val camera = provider!!.bindToLifecycle(lifecycle, CameraSelector.DEFAULT_BACK_CAMERA, preview, image)
            view.setOnTouchListener { _, event -> if (event.action == MotionEvent.ACTION_UP) { val point = view.meteringPointFactory.createPoint(event.x, event.y); camera.cameraControl.startFocusAndMetering(FocusMeteringAction.Builder(point).build()); view.performClick() }; true }
            latestReady(image, camera)
        } catch (_: Exception) { latestError("Camera unavailable. Go back and choose a file, or reopen the camera.") } }, ContextCompat.getMainExecutor(context))
        onDispose { disposed = true; view.setOnTouchListener(null); provider?.unbind(preview, image) }
    }
    AndroidView(factory = { view }, modifier = Modifier.fillMaxSize())
}

@Composable fun CapturePageStrip(state: CaptureState, retake: (Int) -> Unit, remove: (Int) -> Unit, move: (Int, Int) -> Unit) {
    var selected by remember { mutableIntStateOf(-1) }
    var reviewing by remember { mutableStateOf<CapturedPage?>(null) }
    LaunchedEffect(state.pages.size) { selected = -1 }
    if (state.pages.isNotEmpty()) {
        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) { itemsIndexed(state.pages, key = { _, page -> page.id }) { index, page ->
            var bitmap by remember(page.id) { mutableStateOf<Bitmap?>(null) }
            LaunchedEffect(page.id) { bitmap = withContext(Dispatchers.IO) { BitmapFactory.decodeFile(page.thumbnail.path) } }
            Column(Modifier.width(76.dp).clickable(enabled = !state.busy) { selected = if (selected == index) -1 else index }.border(if (selected == index) 2.dp else 1.dp, if (selected == index) Navy else Hairline, RoundedCornerShape(8.dp)).padding(4.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                bitmap?.let { Image(it.asImageBitmap(), "Captured page ${index + 1}", Modifier.height(68.dp).fillMaxWidth(), contentScale = ContentScale.Fit) }
                Text("Page ${index + 1}", style = MaterialTheme.typography.labelSmall)
            }
        } }
        if (selected in state.pages.indices) {
        TextButton(onClick = { reviewing = state.pages[selected] }, enabled = !state.busy) { Text("Review page ${selected + 1}") }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            TextButton(onClick = { retake(selected) }, enabled = !state.busy) { Text("Retake ${selected + 1}") }
            TextButton(onClick = { remove(selected); selected = -1 }, enabled = !state.busy) { Text("Remove") }
            IconButton(onClick = { move(selected, -1); selected-- }, enabled = !state.busy && state.retake == null && selected > 0) { Icon(Icons.Outlined.ArrowBack, "Move page earlier") }
            IconButton(onClick = { move(selected, 1); selected++ }, enabled = !state.busy && state.retake == null && selected < state.pages.lastIndex) { Icon(Icons.Outlined.ArrowForward, "Move page later") }
        }
        }
    }
    reviewing?.let { page -> CapturedPhotoReview(page) { reviewing = null } }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable private fun CapturedPhotoReview(page: CapturedPage, close: () -> Unit) {
    var bitmap by remember(page.id) { mutableStateOf<Bitmap?>(null) }
    var error by remember { mutableStateOf("") }
    var zoom by remember { mutableFloatStateOf(1f) }
    var offset by remember { mutableStateOf(Offset.Zero) }
    LaunchedEffect(page.id) { try { bitmap = withContext(Dispatchers.IO) { CaptureDocuments.decode(page.file, 2200) } } catch (_: Exception) { error = "Could not open this page. Retake it before submitting." } }
    Dialog(onDismissRequest = close, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Scaffold(topBar = { TopAppBar(title = { Text("Review captured page") }, navigationIcon = { TextButton(onClick = close) { Text("Done") } }) }, containerColor = Canvas) { padding ->
            Column(Modifier.fillMaxSize().padding(padding).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("Pinch to zoom and drag. Check small text, dates and all four page edges.", style = MaterialTheme.typography.bodySmall)
                Box(Modifier.weight(1f).fillMaxWidth().clipToBounds().pointerInput(page.id) {
                    detectTransformGestures { _, pan, scale, _ ->
                        zoom = (zoom * scale).coerceIn(1f, 5f)
                        val limitX = size.width * (zoom - 1) / 2; val limitY = size.height * (zoom - 1) / 2
                        offset = Offset((offset.x + pan.x).coerceIn(-limitX, limitX), (offset.y + pan.y).coerceIn(-limitY, limitY))
                    }
                }, contentAlignment = Alignment.Center) {
                    bitmap?.let { Image(it.asImageBitmap(), "Full captured page", modifier = Modifier.fillMaxSize().graphicsLayer { scaleX = zoom; scaleY = zoom; translationX = offset.x; translationY = offset.y }, contentScale = ContentScale.Fit) }
                    if (bitmap == null) Text(error.ifBlank { "Opening page…" })
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                    TextButton(onClick = { zoom = (zoom / 1.5f).coerceAtLeast(1f); offset = Offset.Zero }) { Text("Zoom out") }
                    TextButton(onClick = { zoom = 1f; offset = Offset.Zero }) { Text("Fit page") }
                    TextButton(onClick = { zoom = (zoom * 1.5f).coerceAtMost(5f) }) { Text("Zoom in") }
                }
            }
        }
    }
}
