package `in`.docket.app

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.lifecycle.ViewModelProvider
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.view.WindowCompat

class MainActivity : ComponentActivity() {
    private val model by viewModels<DocketViewModel> { ViewModelProvider.AndroidViewModelFactory(application) }
    private val cameraModel by viewModels<CaptureViewModel> { ViewModelProvider.AndroidViewModelFactory(application) }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        setContent { DocketTheme { DocketApp(model, intent.getStringExtra("case_id"), cameraModel) } }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun DocketApp(vm: DocketViewModel, initialCase: String?, cameraModel: CaptureViewModel) {
    val notices by vm.notices.collectAsState()
    val busy by vm.busy.collectAsState()
    val message by vm.message.collectAsState()
    val apiMode by vm.apiMode.collectAsState()
    val account by vm.account.collectAsState()
    val demo by vm.demo.collectAsState()
    if (account == null && !demo) { AuthScreen(vm, busy, message); return }
    var accountOpen by remember { mutableStateOf(false) }
    if (accountOpen) { AccountScreen(vm, busy) { accountOpen = false }; return }
    val context = LocalContext.current
    val snackbar = remember { SnackbarHostState() }
    val screenState = rememberSaveableStateHolder()
    var tab by rememberSaveable { mutableIntStateOf(0) }
    var selectedId by rememberSaveable { mutableStateOf(initialCase) }
    var intake by rememberSaveable { mutableStateOf(false) }
    var cameraOpen by rememberSaveable { mutableStateOf(false) }
    var intakeUri by rememberSaveable { mutableStateOf<String?>(null) }
    var intakeName by rememberSaveable { mutableStateOf("") }
    var evidenceCase by rememberSaveable { mutableStateOf("") }
    var evidenceDoc by rememberSaveable { mutableStateOf("") }
    var pendingExportId by rememberSaveable { mutableStateOf("") }
    var pendingExportType by rememberSaveable { mutableStateOf("zip") }
    var pendingMail by rememberSaveable { mutableStateOf("") }
    var exportingId by rememberSaveable { mutableStateOf<String?>(null) }
    var exportCenter by rememberSaveable { mutableStateOf(false) }
    var overflow by remember { mutableStateOf(false) }
    var discard by remember { mutableStateOf(false) }
    var reminderVersion by remember { mutableIntStateOf(0) }
    val notice = notices.firstOrNull { it.id == selectedId }
    var draft by rememberSaveable(selectedId) { mutableStateOf(notice?.draft.orEmpty()) }
    val workspaceId = account?.optJSONObject("workspace")?.text("id")
    var activeWorkspace by rememberSaveable { mutableStateOf(workspaceId) }
    LaunchedEffect(workspaceId) { if (activeWorkspace != workspaceId) { selectedId = null; intake = false; cameraOpen = false }; activeWorkspace = workspaceId }
    val dirty = notice != null && draft != notice.draft && !notice.quarantined
    fun back() { if (busy) return; if (dirty) discard = true else { selectedId = null; intake = false; cameraModel.clear(); vm.store.discardCameraDocument(intakeUri?.let(Uri::parse)); intakeUri = null } }
    fun persistRead(uri: Uri) { runCatching { context.contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION) } }
    fun clearCameraFile() { vm.store.discardCameraDocument(intakeUri?.let(Uri::parse)) }
    DisposableEffect(account?.optJSONObject("workspace")?.text("id"), demo) { onDispose { if ((context as? android.app.Activity)?.isChangingConfigurations != true) { cameraModel.clear(); clearCameraFile() } } }
    val intakePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri -> if (uri != null) { clearCameraFile(); cameraModel.clear(); persistRead(uri); intakeUri = uri.toString(); intakeName = context.contentResolver.query(uri, arrayOf(android.provider.OpenableColumns.DISPLAY_NAME), null, null, null)?.use { if (it.moveToFirst()) it.getString(0) else "Selected notice" } ?: "Selected notice" } }
    val evidencePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri -> if (uri != null) { persistRead(uri); vm.attach(evidenceCase, evidenceDoc, uri) } }
    val zipPicker = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/zip")) { uri -> if (uri != null) notices.firstOrNull { it.id == pendingExportId }?.let { vm.export(it, uri, "zip") } }
    val pdfPicker = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/pdf")) { uri -> if (uri != null) notices.firstOrNull { it.id == pendingExportId }?.let { vm.export(it, uri, pendingExportType) } }
    val mailPicker = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/xml")) { uri -> if (uri != null) vm.mailFilter(pendingMail, uri) }
    fun export(id: String, type: String) {
        pendingExportId = id; pendingExportType = type; exportingId = null
        val launch = { if (type == "zip") zipPicker.launch("docket-$id.zip") else pdfPicker.launch("docket-$id-${if (type == "reply") "reply" else "brief"}.pdf") }
        if (id == selectedId && dirty) vm.saveDraft(id, draft, launch) else launch()
    }
    if (cameraOpen) {
        CameraCaptureScreen(cameraModel, close = { cameraOpen = false }, ready = { file ->
            clearCameraFile(); intakeUri = Uri.fromFile(file).toString(); intakeName = "Scanned notice.pdf"; cameraOpen = false
            vm.previewDocument(Uri.fromFile(file))
        })
        return
    }
    LaunchedEffect(message) { message?.let { vm.dismissMessage(); snackbar.showSnackbar(it) } }
    BackHandler(enabled = notice != null || intake) { back() }
    Scaffold(
        containerColor = Canvas,
        topBar = {
            TopAppBar(
                title = {
                    if (notice != null || intake) Text(if (intake) "New notice" else "Case details", style = MaterialTheme.typography.titleLarge)
                    else Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) { Box(Modifier.size(30.dp).background(Navy, RoundedCornerShape(8.dp)), contentAlignment = Alignment.Center) { Text("D", color = Gold, style = MaterialTheme.typography.titleLarge) }; Text("Docket", style = MaterialTheme.typography.titleLarge) }
                },
                navigationIcon = { if (notice != null || intake) IconButton(onClick = ::back, enabled = !busy) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "Back") } },
                actions = {
                    if (notice != null) Box {
                        IconButton(onClick = { overflow = true }, enabled = !busy) { Icon(Icons.Outlined.MoreVert, "Case actions") }
                        DropdownMenu(expanded = overflow, onDismissRequest = { overflow = false }) {
                            DropdownMenuItem(text = { Text("Export case") }, leadingIcon = { Icon(Icons.Outlined.Download, null) }, onClick = { overflow = false; exportingId = notice.id })
                            if (!notice.closed && !notice.quarantined) {
                                DropdownMenuItem(text = { Text("Mark for advisor review") }, leadingIcon = { Icon(Icons.Outlined.PersonOutline, null) }, onClick = { overflow = false; if (dirty) vm.notify("Save your draft before changing the review status.") else vm.state(notice.id, "CA_ESCALATED") })
                                DropdownMenuItem(text = { Text("Mark case closed") }, leadingIcon = { Icon(Icons.Outlined.TaskAlt, null) }, onClick = { overflow = false; if (dirty) vm.notify("Save your draft before closing the case.") else vm.state(notice.id, "SUBMITTED_CLOSED") })
                            }
                        }
                    } else if (!intake) {
                        Text(if (apiMode) "API" else "ON DEVICE", style = MaterialTheme.typography.labelMedium, color = Muted, modifier = Modifier.padding(end = 20.dp))
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Canvas, titleContentColor = Navy, navigationIconContentColor = Navy, actionIconContentColor = Navy)
            )
        },
        bottomBar = {
            if (notice == null && !intake) NavigationBar(containerColor = Navy, contentColor = Color.White, tonalElevation = 0.dp) {
                listOf("Home" to Icons.Outlined.Home, "Notices" to Icons.Outlined.Inbox, "Deadlines" to Icons.Outlined.CalendarMonth, "Workspace" to Icons.Outlined.GridView).forEachIndexed { index, (label, image) ->
                    NavigationBarItem(selected = tab == index, onClick = { tab = index }, icon = { Icon(image, null) }, label = { Text(label) }, colors = NavigationBarItemDefaults.colors(selectedIconColor = Gold, selectedTextColor = Color.White, unselectedIconColor = Color(0xFFABBBD0), unselectedTextColor = Color(0xFFCBD6E5), indicatorColor = Color(0xFF304C70)))
                }
            }
        },
        floatingActionButton = {
            if (notice == null && !intake && tab in listOf(0, 1)) ExtendedFloatingActionButton(onClick = { if (!busy) { screenState.removeState("intake"); clearCameraFile(); cameraModel.clear(); vm.clearOcrPreview(); intake = true; intakeUri = null; intakeName = "" } }, icon = { Icon(Icons.Outlined.Add, null) }, text = { Text("Add notice") }, containerColor = Navy, contentColor = Color.White, shape = RoundedCornerShape(14.dp))
        },
        snackbarHost = { SnackbarHost(snackbar) }
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            screenState.SaveableStateProvider(if (intake) "intake" else if (notice != null) "case:${notice.id}" else "tab:$tab:$apiMode") {
            when {
                intake -> IntakeScreen(vm, busy, apiMode, { intakePicker.launch(arrayOf("application/pdf", "image/*", "text/plain")) }, { cameraOpen = true }, intakeUri?.let(Uri::parse), intakeName, { clearCameraFile(); cameraModel.clear(); intakeUri = null; intakeName = "" }) { id -> clearCameraFile(); cameraModel.clear(); intakeUri = null; intake = false; selectedId = id }
                notice != null -> CaseScreen(notice, busy, draft, { draft = it }, vm, { doc -> evidenceCase = notice.id; evidenceDoc = doc; evidencePicker.launch(arrayOf("application/pdf", "image/*", "text/plain", "text/csv", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")) }, { exportingId = notice.id }, { export(notice.id, "report") })
                tab == 0 -> HomeScreen(notices, { selectedId = it }, { tab = 1 }, apiMode)
                tab == 1 -> NoticesScreen(notices, { selectedId = it }, vm::refresh, busy)
                tab == 2 -> { key(reminderVersion) { DeadlinesScreen(notices, vm.store.preferences.getBoolean("reminders", false), { selectedId = it }, { tab = 3 }) } }
                else -> WorkspaceScreen(vm, apiMode, busy, { if (account == null) vm.signOut() else accountOpen = true }, { exportCenter = true }, { address -> pendingMail = address; mailPicker.launch("docket-gmail-filter.xml") }, { reminderVersion++ })
            }
            }
            if (busy) LinearProgressIndicator(modifier = Modifier.fillMaxWidth().align(Alignment.TopCenter), color = Gold, trackColor = Canvas)
        }
    }
    if (discard) AlertDialog(onDismissRequest = { discard = false }, title = { Text("Keep your draft changes?") }, text = { Text("Save the reply to your case before leaving, or discard the unsaved edits.") }, confirmButton = { TextButton(onClick = { notice?.let { vm.saveDraft(it.id, draft) { selectedId = null } }; discard = false }, enabled = !busy) { Text("Save & leave") } }, dismissButton = { TextButton(onClick = { discard = false; selectedId = null }, enabled = !busy) { Text("Discard edits") } })
    if (exportCenter) AlertDialog(onDismissRequest = { exportCenter = false }, title = { Text("Choose a case to export") }, text = { LazyColumn(Modifier.heightIn(max = 380.dp)) { items(notices, key = { it.id }) { item -> ListItem(headlineContent = { Text(item.title) }, supportingContent = { Text(item.service) }, modifier = Modifier.clickable { exportingId = item.id; exportCenter = false }) } } }, confirmButton = { TextButton(onClick = { exportCenter = false }) { Text("Close") } })
    exportingId?.let { id -> notices.firstOrNull { it.id == id }?.let { item ->
        AlertDialog(onDismissRequest = { exportingId = null }, title = { Text("Export case") }, text = { Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("${item.title}\nSave to a location you choose. Nothing is sent automatically.", style = MaterialTheme.typography.bodyMedium)
            if (id == selectedId && dirty) Text("Your draft will be saved before exporting.", style = MaterialTheme.typography.bodySmall, color = GoldInk)
            Button(onClick = { export(id, "zip") }, modifier = Modifier.fillMaxWidth(), enabled = !busy) { Text("Complete case package · ZIP") }
            OutlinedButton(onClick = { export(id, "report") }, modifier = Modifier.fillMaxWidth(), enabled = !busy) { Text("Case brief · PDF") }
            if (!item.quarantined) OutlinedButton(onClick = { export(id, "reply") }, modifier = Modifier.fillMaxWidth(), enabled = !busy) { Text("Saved reply · PDF") }
        } }, confirmButton = { TextButton(onClick = { exportingId = null }) { Text("Cancel") } })
    } }
}
